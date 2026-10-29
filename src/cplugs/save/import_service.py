"""Taking the old archive into the vault: preview, apply, undo and the receipts (S4). One service for the routes and the MCP tools, so there
is no second implementation. Everything blocking runs off the loop. ONE IMPORT RUNS AT A TIME; a second caller is refused, never queued.

PREVIEW reads every configured source READ ONLY and writes nothing into the vault or a source; it answers the counts and a fingerprint, and keeps
the last few (counts only) in the state folder so an approval card replayed after a restart still finds its preview. APPLY needs that fingerprint: it plans again, refuses when the plan is not the one previewed (``plan_changed``) and only
then files, add only, through ``adopt_points``, with the undo log outside the vault. A source path is checked: absolute, no ``..``, and never
inside the vault. Step 7 plan: ``~/work``.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import structlog

from src.cplugs.save.service import RUNTIME
from src.cplugs.save.vault.old_sources import allowlist, apply as apply_mod, assemble, counts, extras, preview_store, review, runs, verify as verify_mod
from src.cplugs.save.vault.store import Vault
from src.cplugs.sdk import transcript_files as tf, vault_sources

logger = structlog.get_logger()

_BUSY = threading.Lock()
_PREVIEWS: Dict[str, Dict[str, Any]] = {}
_PREVIEWS_KEPT = 8


class ImportRefused(RuntimeError):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _check_path(raw: str, vault_root: Path) -> Path:
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts or not path.exists():
        raise ImportRefused("bad_path", f"{raw!r} is not an existing absolute path")
    real, vault = Path(os.path.realpath(path)), Path(os.path.realpath(vault_root))
    if real == vault or vault in real.parents or real in vault.parents:
        raise ImportRefused("bad_path", f"{raw!r} and the vault overlap; the vault is never a source")
    return path


def config_of(body: Dict[str, Any], vault_root: Path) -> assemble.SourceConfig:
    def one(key: str) -> Optional[Path]:
        return _check_path(body[key], vault_root) if body.get(key) else None

    def many(key: str) -> List[Path]:
        return [_check_path(p, vault_root) for p in body.get(key) or []]

    try:
        only = allowlist.normalize(body["only_points"]) if body.get("only_points") is not None else None
    except allowlist.AllowListError as exc:
        raise ImportRefused(exc.code, exc.detail) from exc
    return assemble.SourceConfig(only_points=only, 
        archives=many("archives"), folders=[(str(f.get("name") or Path(f["path"]).name), _check_path(f["path"], vault_root))
                                            for f in body.get("folders") or []],
        old_stores=many("old_stores"), tar_roots=many("tar_roots"), recovered_root=one("recovered_root"), plan_applied=one("plan_applied"),
        trash_manifests=many("trash_manifests"), rows_file=one("rows_file"), secret_rows=[str(r) for r in body.get("secret_rows") or []],
        reorg_rules=many("reorg_rules"), newest_only=bool(body.get("newest_only", True)), quick=bool(body.get("quick", False)))


def _built(vault: Vault, config: assemble.SourceConfig) -> assemble.Built:
    state = tf.state_dir()
    live = [row for row in vault_sources.project_roots(state) if not row.get("archived_at")]
    try:
        return assemble.build(config, vault, RUNTIME.sources(), live)
    except allowlist.AllowListError as exc:
        raise ImportRefused(exc.code, exc.detail) from exc


def preview_blocking(body: Dict[str, Any]) -> Dict[str, Any]:
    vault = RUNTIME.vault()
    config = config_of(body, vault.root)
    built = _built(vault, config)
    answer = {"fingerprint": counts.fingerprint(built.plan, built.extra_files), "quick": config.quick,
              "counts": counts.summarize(built.plan, built.extra_files)}
    if not config.quick:
        state = Path(tf.state_dir())
        for stored, stored_counts in preview_store.load(state).items():
            _PREVIEWS.setdefault(stored, stored_counts)
        _PREVIEWS.pop(answer["fingerprint"], None)
        _PREVIEWS[answer["fingerprint"]] = answer["counts"]
        while len(_PREVIEWS) > _PREVIEWS_KEPT:
            _PREVIEWS.pop(next(iter(_PREVIEWS)))
        preview_store.save(state, _PREVIEWS)
    return answer


def previewed(fingerprint: str) -> Optional[Dict[str, Any]]:
    found = _PREVIEWS.get(fingerprint)
    if found is None:
        found = preview_store.load(Path(tf.state_dir())).get(fingerprint)
    return found


def apply_blocking(body: Dict[str, Any], fingerprint: str) -> Dict[str, Any]:
    if not _BUSY.acquire(blocking=False):
        raise ImportRefused("import_busy", "an import is already running")
    try:
        vault, state = RUNTIME.vault(), Path(tf.state_dir())
        config = config_of({**body, "quick": False}, vault.root)
        built = _built(vault, config)
        if counts.fingerprint(built.plan, built.extra_files) != fingerprint:
            raise ImportRefused("plan_changed", "the sources are not what the preview saw; preview again")
        run_id = runs.new_run_id()
        roots = vault_sources.claude_roots()
        incoming = [apply_mod.to_incoming(p, run_id, Path(roots[0]), Path(vault_sources.codex_home())) for p in built.plan.points]
        extras_point = extras.point_of(config.recovered_root, built.extra_files, run_id) if config.recovered_root else None
        if extras_point is not None:
            incoming.append(extras_point)
        summary = counts.summarize(built.plan, built.extra_files)
        runs.write_expected(state, run_id, apply_mod.expected_rows(incoming))
        results = apply_mod.file_points(vault, state, run_id, incoming)
        receipt = apply_mod.receipt_of(run_id, results, summary, extras.UNIT if extras_point else None)
        runs.write_receipt(state, run_id, receipt)
        logger.info("save_import_finished", run_id=run_id, state=receipt["state"], filed=receipt["filed"])
        return receipt
    finally:
        _BUSY.release()


def undo_blocking(run_id: str) -> Dict[str, Any]:
    if not _BUSY.acquire(blocking=False):
        raise ImportRefused("import_busy", "an import is already running")
    try:
        try:
            return apply_mod.undo(RUNTIME.vault(), Path(tf.state_dir()), run_id)
        except KeyError as exc:
            raise ImportRefused("no_such_run", f"no import run {run_id}") from exc
        except runs.RunError as exc:
            raise ImportRefused("nothing_to_undo", str(exc)) from exc
    finally:
        _BUSY.release()


def verify_blocking(run_id: str) -> Dict[str, Any]:
    try:
        return verify_mod.verify_run(RUNTIME.vault(), Path(tf.state_dir()), run_id)
    except (KeyError, runs.RunError) as exc:
        raise ImportRefused("no_such_run", f"no import run {run_id}") from exc


def review_blocking(units: List[str], verdict: str, date: str) -> Dict[str, Any]:
    if verdict not in review.VERDICTS or not review.DATE_RE.match(date):
        raise ImportRefused("bad_verdict", f"a verdict is one of {review.VERDICTS} with a date like 20261022")
    return review.add_verdicts(RUNTIME.vault(), units, verdict, date)


def receipts_blocking(run_id: Optional[str] = None) -> Any:
    state = Path(tf.state_dir())
    if run_id is None:
        return runs.list_receipts(state)
    try:
        return runs.read_receipt(state, run_id)
    except KeyError as exc:
        raise ImportRefused("no_such_run", f"no import run {run_id}") from exc
    except runs.RunError as exc:
        raise ImportRefused("no_such_run", str(exc)) from exc


__all__: Sequence[str] = ["ImportRefused", "apply_blocking", "config_of", "preview_blocking", "previewed", "receipts_blocking", "review_blocking", "undo_blocking", "verify_blocking"]
