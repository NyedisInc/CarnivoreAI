
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

import structlog

from src.cplugs.crate import constants as K
from src.cplugs.crate import import_store
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.jobs.runner import JobFailed
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_import as ci

logger = structlog.get_logger()


class _Progress:

    def __init__(self, handle: JobHandle) -> None:
        self.handle = handle

    def __call__(self, nbytes: int) -> None:
        self.handle.add(nbytes)
        self.handle.check()


class JobHooks(ci.ApplyHooks):

    def __init__(self, handle: JobHandle, work: Path, import_id: str) -> None:
        self.handle, self.work, self.import_id = handle, work, import_id

    def phase(self, name: str, total: int = 0, files: int = 0) -> None:
        self.handle.phase(name, total=total, files=files)

    def add(self, nbytes: int, files: int = 0) -> None:
        self.handle.add(nbytes, files=files)

    def check(self) -> None:
        self.handle.check()

    def undo(self, entry: Dict[str, Any]) -> None:
        import_store.append_undo(self.work, self.import_id, entry)


def verify_full(path: Path, expected: Optional[str], key: Optional[bytes], handle: JobHandle) -> None:
    handle.phase(K.PHASE_VERIFYING, total=path.stat().st_size)
    report = cf.verify(path, "full", expected_sha256=expected, identity=key, progress=_Progress(handle))
    if not report.ok:
        raise JobFailed(report.problems[0]["code"] or "verify_failed", "the crate did not pass a full check; nothing was written")


def finished(receipt: ci.ImportReceipt, now: str) -> Dict[str, Any]:
    return {**receipt.as_json(), "finished_at": now}


def make_work(env: CrateEnv, import_env: ci.ImportEnv, path: Path, key: Optional[bytes], expected: Optional[str], sha256: str,
              request: ci.ImportRequest, fingerprint: str, import_id: str, now: Callable[[], str]) -> Callable[[JobHandle], Dict[str, Any]]:
    def work(handle: JobHandle) -> Dict[str, Any]:
        verify_full(path, expected, key, handle)
        hooks = JobHooks(handle, env.work, import_id)
        with cf.open_crate(path, key) as reader:
            try:
                receipt = ci.apply_import(reader, import_env, request, crate_sha256=sha256, fingerprint=fingerprint,
                                          import_id=import_id, hooks=hooks)
            except ci.ImportRefused as exc:
                raise JobFailed(exc.code, exc.detail) from exc
            except ci.ImportFailed as exc:
                if exc.rolled_back:
                    raise JobFailed(exc.code, exc.detail) from exc
                logger.warning("crate_import_rolling_forward", import_id=import_id, code=exc.code)
                try:
                    receipt = ci.finish_import(reader, import_env, request, crate_sha256=sha256, import_id=import_id, hooks=hooks)
                except (ci.ImportRefused, ci.ImportFailed) as again:
                    raise JobFailed(again.code, f"{again.detail}; the rows are saved, restore the same crate again to finish") from again
        stored = finished(receipt, now())
        import_store.write_receipt(env.work, import_id, stored)
        return stored

    return work
