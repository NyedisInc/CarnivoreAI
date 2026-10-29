
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import structlog

from src.cplugs.reviewboard import attachment_guard, attachment_types as types, office_text
from src.cplugs.reviewboard.errors import SecretInFile, UnscannableFile
from src.cplugs.sdk.file_secrets import Deadline, ScanTimeout, credential_counts

logger = structlog.get_logger()


def _scannable_texts(name: str, data: bytes, deadline: Deadline) -> Optional[Tuple[str, ...]]:
    kind = types.CLASS_BY_EXTENSION.get(attachment_guard.extension_of(name))
    if kind == types.TEXT:
        return (data.decode("utf-8"),)
    if kind == types.OFFICE:
        return office_text.office_texts(data, deadline)
    return None


def _highest_counts(readings: Sequence[str], deadline: Deadline) -> Dict[str, int]:
    best: Dict[str, int] = {}
    for text in readings:
        for detector, count in credential_counts(text, deadline).items():
            best[detector] = max(best.get(detector, 0), count)
    return best


def findings(checked: Sequence[Tuple[str, bytes]]) -> List[Tuple[str, Dict[str, int]]]:
    out: List[Tuple[str, Dict[str, int]]] = []
    unreadable: List[Dict[str, str]] = []
    deadline = Deadline()
    for name, data in checked:
        try:
            texts = _scannable_texts(name, data, deadline)
            counts = _highest_counts(texts, deadline) if texts is not None else {}
        except office_text.OfficeUnreadable as exc:
            unreadable.append({"file": name[:80], "reason": exc.reason})
            continue
        except ScanTimeout:
            unreadable.append({"file": name[:80], "reason": office_text.REASON_TIMEOUT})
            continue
        if counts:
            out.append((name[:80], counts))
    if unreadable:
        logger.warning("reviewboard_attach_unscannable_refused", files=[u["file"] for u in unreadable], reasons=sorted({u["reason"] for u in unreadable}))
        raise UnscannableFile(f"{', '.join(u['file'] for u in unreadable)} could not be read for a credential check, so nothing was attached; "
                              "re-save it without a password and attach again", files=unreadable)
    return out


def refuse_secrets(checked: Sequence[Tuple[str, bytes]], *, slug: str) -> None:
    found = findings(checked)
    if not found:
        return
    logger.warning("reviewboard_attach_secret_refused", slug=slug, files=[name for name, _ in found],
                   detectors=sorted({d for _, counts in found for d in counts}))
    names = ", ".join(name for name, _ in found)
    raise SecretInFile(f"{names} looks like it holds a credential, so nothing was attached; remove it and attach again",
                       files=[{"file": name, "detectors": counts} for name, counts in found])
