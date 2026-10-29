
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

import structlog

from src.core.pipeline import contract as C
from src.core.pipeline import inherit, log, plugin_db, reader
from src.core.pipeline.contract import Appended, ConversationRemoved, Event, FileRemoved, FileReset, Lineage
from src.core.transcript_contract import parse_range

logger = structlog.get_logger()

SKIP_BUDGET, SKIP_GONE, SKIP_ICLOUD, SKIP_TIMEOUT, SKIP_UNREADABLE = "budget", "gone", "icloud", "timeout", "unreadable"


@dataclass(frozen=True)
class FileTarget:

    path: str
    conversation_id: str
    family: str
    file_kind: str
    rewritten: bool = False


@dataclass
class Budget:

    left: int = C.RUN_BUDGET_BYTES

    def spend(self, n: int) -> None:
        self.left -= n

    @property
    def exhausted(self) -> bool:
        return self.left <= 0


@dataclass
class PluginRun:

    plugin: C.Plugin
    events: int = 0
    lines: int = 0
    own_lines: int = 0
    resets: int = 0
    removed: int = 0
    raced: int = 0
    failed: Optional[str] = None
    busy_seconds: float = 0.0
    read_conn: Optional[sqlite3.Connection] = field(default=None, repr=False)

    def drop_read_conn(self, state_dir: Optional[Path] = None) -> None:
        conn, self.read_conn = self.read_conn, None
        if conn is not None and state_dir is not None:
            plugin_db.discard_pooled(state_dir, self.plugin)


@dataclass
class Delivery:

    state_dir: Path
    runs: List[PluginRun]
    trigger: str
    lineage: Optional[Lineage] = None
    budget: Budget = field(default_factory=Budget)
    clock: Callable[[], float] = time.time
    timer: Callable[[], float] = time.monotonic
    bytes_read: int = 0
    skipped_files: Dict[str, int] = field(default_factory=dict)

    def live_runs(self, target: FileTarget) -> List[PluginRun]:
        return [r for r in self.runs if r.failed is None and r.plugin.reads(target.family, target.file_kind)]

    def close_reads(self) -> None:
        for run in self.runs:
            run.drop_read_conn()

    def skip(self, reason: str) -> str:
        self.skipped_files[reason] = self.skipped_files.get(reason, 0) + 1
        return reason


@contextmanager
def _busy(delivery: Delivery, run: PluginRun) -> Iterator[None]:
    started = delivery.timer()
    try:
        yield
    finally:
        run.busy_seconds += max(0.0, delivery.timer() - started)


def _fail(run: PluginRun, exc: BaseException) -> None:
    run.failed = f"{type(exc).__name__}: {exc}"[: C.ERROR_CHARS]
    log.log_error("pipeline_plugin_failed", plugin=run.plugin.id, error=exc)


def _discard_if_sqlite(delivery: Delivery, run: PluginRun, exc: BaseException) -> None:
    if isinstance(exc, (sqlite3.Error, plugin_db.PluginUnavailable)):
        plugin_db.discard_pooled(delivery.state_dir, run.plugin)


def _read_cursor(delivery: Delivery, run: PluginRun, path: str) -> Tuple[bool, Optional[plugin_db.Cursor]]:
    try:
        with plugin_db.lock_for(run.plugin.id):
            if run.read_conn is None:
                run.read_conn = plugin_db.pooled_db(delivery.state_dir, run.plugin)
            return True, plugin_db.get_cursor(run.read_conn, path)
    except (plugin_db.PluginUnavailable, sqlite3.Error) as exc:
        run.drop_read_conn(delivery.state_dir)
        _fail(run, exc)
        return False, None


def _apply(delivery: Delivery, run: PluginRun, expected: Optional[tuple], event: Event,
           cursor: plugin_db.Cursor) -> bool:
    from src.core.db import transaction

    with _busy(delivery, run):
        try:
            with plugin_db.lock_for(run.plugin.id):
                conn = plugin_db.pooled_db(delivery.state_dir, run.plugin)
                with transaction(conn):
                    held = plugin_db.get_cursor(conn, cursor.path)
                    if (held.position() if held else None) != expected:
                        run.raced += 1
                        return False
                    run.plugin.on_events(conn, (event,))
                    cursor.updated_at = delivery.clock()
                    plugin_db.save_cursor(conn, cursor)
                    plugin_db.set_meta(conn, C.META_LAST_DELIVERY_AT, cursor.updated_at)
        except Exception as exc:  # noqa: BLE001
            _discard_if_sqlite(delivery, run, exc)
            _fail(run, exc)
            return False
        return True


def _catch_up(delivery: Delivery, run: PluginRun, event: Appended) -> bool:
    hook = run.plugin.catch_up
    if hook is None:
        return True
    with _busy(delivery, run):
        try:
            with plugin_db.lock_for(run.plugin.id):
                if run.read_conn is None:
                    run.read_conn = plugin_db.pooled_db(delivery.state_dir, run.plugin)
            result = hook(run.read_conn, event, max(1, delivery.budget.left))
        except reader.ReadTimeout:
            run.drop_read_conn(delivery.state_dir)
            raise
        except Exception as exc:  # noqa: BLE001
            run.drop_read_conn(delivery.state_dir)
            _fail(run, exc)
            return False
    delivery.budget.spend(result.bytes_read)
    delivery.bytes_read += result.bytes_read
    return result.ready


def _reset(delivery: Delivery, group: List[PluginRun], expected: Optional[tuple], target: FileTarget,
           consumed: int, size: int, name: str) -> List[PluginRun]:
    event = FileReset(name, target.conversation_id, target.family, target.path, target.file_kind, consumed, size)
    done = []
    for run in group:
        fresh = plugin_db.Cursor(target.path, target.conversation_id, target.family, target.file_kind)
        if _apply(delivery, run, expected, event, fresh):
            run.resets += 1
            done.append(run)
    logger.info("pipeline_plugin_file_reset", path=target.path, reset=name, plugins=[r.plugin.id for r in done])
    return done


def _deliver_group(delivery: Delivery, target: FileTarget, size: int, cursor: Optional[plugin_db.Cursor],
                   group: List[PluginRun]) -> None:
    expected = cursor.position() if cursor else None
    state = cursor or plugin_db.Cursor(target.path, target.conversation_id, target.family, target.file_kind)
    if cursor is not None and cursor.offset:
        check = reader.timed(reader.check_cursor, target.path, size, cursor.offset, cursor.last_serial,
                             cursor.last_serial_offset, key=target.path)
        delivery.bytes_read += check.checked_bytes
        if check.reset is not None:
            group = _reset(delivery, group, expected, target, cursor.offset, size, check.reset)
            state = plugin_db.Cursor(target.path, target.conversation_id, target.family, target.file_kind)
            expected = state.position()
    while group and not delivery.budget.exhausted and state.offset < size:
        data = reader.timed(reader.read_slice, target.path, state.offset, size,
                            min(C.SLICE_BYTES, max(1, delivery.budget.left)), key=target.path)
        delivery.budget.spend(len(data))
        delivery.bytes_read += len(data)
        if not data:
            break
        rng = parse_range(data, state.offset, target.family)
        inherit_state, inherited_start, inherited_end = inherit.advance(
            state.inherit_state, state.inherited_start, state.inherited_end, rng.lines, target.conversation_id)
        event = Appended(target.conversation_id, target.family, target.path, target.file_kind, state.offset,
                         rng.complete_end, rng.lines, inherited_start, inherited_end, delivery.lineage,
                         delivery.trigger)
        own = len(event.own_lines)
        nxt = plugin_db.Cursor(target.path, target.conversation_id, target.family, target.file_kind,
                               rng.complete_end, state.lines + len(rng.lines), rng.last_serial,
                               rng.lines[-1].offset, inherit_state, inherited_start, inherited_end)
        kept = []
        for run in group:
            if not _catch_up(delivery, run, event):
                if run.failed is None:
                    delivery.skip(SKIP_BUDGET)
                continue
            if _apply(delivery, run, expected, event, replace(nxt)):
                run.events += 1
                run.lines += len(rng.lines)
                run.own_lines += own
                kept.append(run)
        group, state, expected = kept, nxt, nxt.position()
    if group and delivery.budget.exhausted and state.offset < size:
        delivery.skip(SKIP_BUDGET)


def deliver_file(delivery: Delivery, target: FileTarget) -> Optional[str]:
    from src.core.transcript_source import dataless

    runs = delivery.live_runs(target)
    if not runs:
        return None
    if delivery.budget.exhausted:
        return delivery.skip(SKIP_BUDGET)
    try:
        size = os.stat(target.path).st_size
    except FileNotFoundError:
        return delivery.skip(SKIP_GONE)
    except OSError as exc:
        return _unreadable(delivery, target, exc, dataless)
    groups: Dict[Optional[tuple], Tuple[Optional[plugin_db.Cursor], List[PluginRun]]] = {}
    for run in runs:
        ok, cursor = _read_cursor(delivery, run, target.path)
        if not ok:
            continue
        if cursor is not None and cursor.offset == size and not target.rewritten:
            continue
        key = cursor.position() if cursor else None
        groups.setdefault(key, (cursor, []))[1].append(run)
    for cursor, group in groups.values():
        try:
            _deliver_group(delivery, target, size, cursor, group)
        except reader.ReadTimeout:
            reader.request_download(target.path)
            return delivery.skip(SKIP_TIMEOUT)
        except OSError as exc:
            return _unreadable(delivery, target, exc, dataless)
    return None


def _unreadable(delivery: Delivery, target: FileTarget, exc: OSError, dataless) -> str:
    if dataless.is_deadlock(exc):
        reader.request_download(target.path)
        return delivery.skip(SKIP_ICLOUD)
    logger.warning("pipeline_plugin_file_unreadable", path=target.path, error=str(exc))
    return delivery.skip(SKIP_UNREADABLE)


def deliver_removed(delivery: Delivery, conversation_id: str) -> None:
    from src.core.db import transaction

    for run in delivery.runs:
        if run.failed is not None or run.plugin.per_file_removal:
            continue
        with _busy(delivery, run):
            try:
                with plugin_db.lock_for(run.plugin.id):
                    conn = plugin_db.pooled_db(delivery.state_dir, run.plugin)
                    with transaction(conn):
                        paths = tuple(r[0] for r in conn.execute(
                            f"SELECT path FROM {C.CURSORS_TABLE} WHERE conversation_id = ? ORDER BY path",
                            (conversation_id,)))
                        if paths:
                            run.plugin.on_events(conn, (ConversationRemoved(conversation_id, paths),))
                            plugin_db.delete_cursors(conn, conversation_id)
                            run.removed += 1
            except Exception as exc:  # noqa: BLE001
                _discard_if_sqlite(delivery, run, exc)
                _fail(run, exc)


def deliver_file_removed(delivery: Delivery, target: FileTarget) -> None:
    from src.core.db import transaction

    try:
        os.stat(target.path)
        return
    except FileNotFoundError:
        pass
    except OSError:
        return
    for run in delivery.runs:
        if run.failed is not None or not run.plugin.per_file_removal:
            continue
        with _busy(delivery, run):
            try:
                with plugin_db.lock_for(run.plugin.id):
                    conn = plugin_db.pooled_db(delivery.state_dir, run.plugin)
                    with transaction(conn):
                        held = plugin_db.get_cursor(conn, target.path)
                        if held is not None:
                            run.plugin.on_events(conn, (FileRemoved(held.conversation_id, target.path, held.file_kind),))
                            plugin_db.delete_cursor(conn, target.path)
                            run.removed += 1
            except Exception as exc:  # noqa: BLE001
                _discard_if_sqlite(delivery, run, exc)
                _fail(run, exc)
