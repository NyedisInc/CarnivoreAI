
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import structlog

from src.core.db import transaction
from src.core.deepsearch import constants as K
from src.core.deepsearch import index_scope, legacy_copies
from src.core.deepsearch import rules as rules_mod
from src.core.deepsearch.byte_source import ByteSource, SourceGone, VaultSource, open_source
from src.core.deepsearch.live import store
from src.core.deepsearch.live.indexer import FileSpec, index_file
from src.core.deepsearch.live.watermark import line_holds
from src.core.deepsearch.transcript_folders import folders_in_lines
from src.core.deepsearch import fallback_hook as fb

logger = structlog.get_logger()

IsLive = Callable[[sqlite3.Connection, fb.FallbackConversation], bool]

_last_listing: float = float("-inf")
_retired: bool = False
_last_sources: Optional[Tuple[Tuple[int, ...], bool]] = None
_failed: Set[Tuple[str, str]] = set()
_confirmed: Set[Tuple[int, str, int, Optional[int], Optional[str]]] = set()
_settled: Dict[str, Tuple[str, str]] = {}
_known: Dict[str, fb.FallbackConversation] = {}


def reset() -> None:
    global _last_listing, _retired, _last_sources
    _last_listing, _retired, _last_sources = float("-inf"), False, None
    _failed.clear()
    _confirmed.clear()
    _settled.clear()
    _known.clear()


def described(conversation_ids: Iterable[str]) -> Dict[str, fb.FallbackConversation]:
    return {c: _known[c] for c in conversation_ids if c in _known}


def default_is_live(conn: sqlite3.Connection, conv: fb.FallbackConversation) -> bool:
    from src.core.session_transcript_presence import family_conversation_presence
    from src.core.transcript_manifest import lookup

    if _original_on_disk(conn, conv.conversation_id):
        return True
    if lookup.transcript_path(conv.conversation_id, conv.family) is not None:
        return True
    try:
        return not family_conversation_presence(conv.family, conv.conversation_id, working_dir=conv.working_dir).missing
    except OSError as exc:
        logger.warning("deepsearch_vault_presence_unreadable", conversation_id=conv.conversation_id, error=str(exc))
        return True


def _on_disk(rows: Iterable[store.LiveFile]) -> bool:
    return any(live.file_kind == K.FILE_CONVERSATION and live.base_point_id != K.VAULT_MARK and os.path.isfile(live.path)
               for live in rows)


def _original_on_disk(conn: sqlite3.Connection, conversation_id: str) -> bool:
    return _on_disk(store.of_conversation(conn, conversation_id))


def _proof_key(live: store.LiveFile) -> Tuple[int, str, int, Optional[int], Optional[str]]:
    return int(live.id), live.path, int(live.indexed_offset), live.last_serial_offset, live.last_serial


def _drop(conn: sqlite3.Connection, rows: Iterable[store.LiveFile]) -> int:
    ids = [int(r.id) for r in rows]
    if ids:
        with transaction(conn):
            for live_id in ids:
                store.delete_file(conn, live_id)
        gone = set(ids)
        _confirmed.difference_update({key for key in _confirmed if key[0] in gone})
    return len(ids)


def _place(live: store.LiveFile) -> Tuple[str, str, str]:
    return live.conversation_id, live.file_kind, fb.path_tail(live.path, live.conversation_id)


def _shadowed(conn: sqlite3.Connection, marked: List[store.LiveFile]) -> List[store.LiveFile]:
    shadows: List[store.LiveFile] = []
    by_conversation: Dict[str, Set[Tuple[str, str, str]]] = {}
    for conv in {m.conversation_id for m in marked}:
        by_conversation[conv] = {_place(r) for r in store.of_conversation(conn, conv) if r.base_point_id != K.VAULT_MARK}
    for live in marked:
        if _place(live) in by_conversation[live.conversation_id]:
            shadows.append(live)
    return shadows


def _confirm(conn: sqlite3.Connection, marked: List[store.LiveFile], active: List[fb.FallbackSource]) -> int:
    todo = [m for m in marked if _proof_key(m) not in _confirmed][:K.VAULT_CONFIRM_PER_PASS]
    failed: List[store.LiveFile] = []
    for live in todo:
        try:
            source = open_source(live.path, K.VAULT_MARK, live.conversation_id, live.file_kind, sources=active)
            held = source.length >= live.indexed_offset
            if held and live.in_scope and live.indexed_offset > 0:
                held, _read = line_holds(source, live.last_serial_offset, live.indexed_offset, live.last_serial)
        except SourceGone:
            held = False
        except OSError as exc:
            logger.warning("deepsearch_vault_unreachable", error=str(exc)[:200])
            return _drop(conn, failed)
        if held:
            _confirmed.add(_proof_key(live))
        else:
            failed.append(live)
    if failed:
        logger.info("deepsearch_vault_rows_dropped", rows=len(failed), reason="not_held_by_the_vault")
    return _drop(conn, failed)


def _record_folders(conn: sqlite3.Connection, path: str, source: ByteSource, start: int) -> None:
    live = store.get(conn, path)
    if live is None or not live.in_scope or live.indexed_offset <= start:
        return
    folders = folders_in_lines(line for _, line in source.lines(start, live.indexed_offset))
    with transaction(conn):
        store.add_folders(conn, int(live.id), folders)


def _index_step(conn: sqlite3.Connection, spec: FileSpec, source: ByteSource, budget: int,
                overrides: Optional[dict], scope: str) -> int:
    live = store.get(conn, spec.path)
    start = live.indexed_offset if live is not None and live.in_scope else 0
    end = min(source.length, start + max(1, budget))
    while True:
        result = index_file(conn, FileSpec(spec.conversation_id, spec.path, spec.file_kind, spec.family, end),
                            overrides=overrides, scope=scope, source=source, mark=K.VAULT_MARK)
        if result.lines or end >= source.length or result.skipped == K.SKIP_LIVE_OUT_OF_SCOPE:
            break
        end = min(source.length, start + 2 * (end - start))
    _record_folders(conn, spec.path, source, result.start)
    return result.bytes_read


def _wanted(active: List[fb.FallbackSource]) -> Dict[str, Tuple[fb.FallbackConversation, fb.FallbackSource]]:
    wanted: Dict[str, Tuple[fb.FallbackConversation, fb.FallbackSource]] = {}
    for source in active:
        try:
            for conv in source.conversations():
                if conv.conversation_id not in wanted:
                    wanted[conv.conversation_id] = (conv, source)
                    _known[conv.conversation_id] = conv
        except OSError as exc:
            logger.warning("deepsearch_vault_listing_failed", error=str(exc)[:200])
    return wanted


def _index_conversation(conn: sqlite3.Connection, conv: fb.FallbackConversation, source: fb.FallbackSource, budget: int,
                        overrides: Optional[dict], scope: str) -> Tuple[int, bool]:
    spent, complete = 0, True
    disk = {_place(r) for r in store.of_conversation(conn, conv.conversation_id) if r.base_point_id != K.VAULT_MARK}
    for file in source.files(conv.conversation_id):
        if (conv.conversation_id, file.file_kind, fb.path_tail(file.source_path, conv.conversation_id)) in disk:
            continue
        row = store.get(conn, file.source_path)
        if row is not None and row.base_point_id != K.VAULT_MARK:
            continue
        decided_out = row is not None and not row.in_scope and row.scope == scope
        if row is not None and (decided_out or (row.in_scope and row.indexed_offset >= file.length)):
            continue
        if spent >= budget:
            complete = False
            continue
        reader = VaultSource(source.reader(conv.conversation_id, file.source_path, file.file_kind))
        spec = FileSpec(conv.conversation_id, file.source_path, file.file_kind, file.family)
        spent += _index_step(conn, spec, reader, budget - spent, overrides, scope)
        after = store.get(conn, file.source_path)
        if after is not None and after.in_scope and after.indexed_offset < reader.length:
            complete = False
    return spent, complete


def sweep(conn: sqlite3.Connection, state_dir: Path, *, sources: Optional[Iterable[fb.FallbackSource]] = None,
          is_live: IsLive = default_is_live, now: Callable[[], float] = time.monotonic,
          min_interval: float = K.VAULT_LIST_INTERVAL_SECONDS, booting: Optional[bool] = None) -> int:
    global _last_listing, _retired, _last_sources
    if not _retired:
        legacy_copies.retire(conn, state_dir)
        _retired = True
    active: List[fb.FallbackSource] = list(fb.sources() if sources is None else sources)
    starting = fb.booting() if booting is None else booting
    if not active:
        _last_sources = None
        marked = store.marked(conn, K.VAULT_MARK)
        if not starting and marked:
            logger.info("deepsearch_vault_rows_dropped", rows=_drop(conn, marked), reason="backup_off")
        return 0
    gate_open = now() - _last_listing >= min_interval
    sources_key = (tuple(id(source) for source in active), starting)
    if gate_open or sources_key != _last_sources:
        _last_sources = sources_key
        marked = store.marked(conn, K.VAULT_MARK)
        _drop(conn, _shadowed(conn, marked))
        marked = store.marked(conn, K.VAULT_MARK)
        _confirm(conn, marked, active)
    if not gate_open:
        return 0
    _last_listing = now()
    overrides = rules_mod.read_overrides()
    scope = index_scope.current()
    done, spent = 0, 0
    for conv_id, (conv, source) in _wanted(active).items():
        key = (conv_id, conv.signature)
        if key in _failed or conv.hidden:
            continue
        rows = store.of_conversation(conn, conv_id)
        if _settled.get(conv_id) == (conv.signature, scope) and rows:
            continue
        if _on_disk(rows) or is_live(conn, conv):
            continue
        if spent >= K.VAULT_PASS_BYTES:
            break
        try:
            read, complete = _index_conversation(conn, conv, source, K.VAULT_PASS_BYTES - spent, overrides, scope)
        except (fb.FallbackUnavailable, OSError, sqlite3.Error) as exc:
            _failed.add(key)
            logger.warning("deepsearch_vault_index_failed", conversation_id=conv_id, error=str(exc)[:300])
            continue
        spent += read
        if complete:
            _settled[conv_id] = (conv.signature, scope)
        if read:
            done += 1
            logger.info("deepsearch_vault_indexed", conversation_id=conv_id, bytes=read)
    return done
