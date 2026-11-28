
from __future__ import annotations

from pathlib import Path

from src.core.backup_health import constants as K
from src.core.backup_health.checks import FIRING, OK, Verdict
from src.core.transcript_manifest import gone_guard


def check_transcripts_unprotected(state_dir: Path) -> Verdict:
    record = gone_guard.read_record(state_dir)
    count = record.get("count")
    if not isinstance(count, int) or count <= 0:
        return Verdict(K.KEY_TRANSCRIPTS_GONE_UNPROTECTED, OK)
    samples = ", ".join(str(s) for s in (record.get("samples") or [])[: gone_guard.SAMPLES])
    more = record.get("overflow")
    if isinstance(more, int) and more > 0:
        return Verdict(K.KEY_TRANSCRIPTS_GONE_UNPROTECTED, FIRING, "error", K.TITLE_TRANSCRIPTS_GONE_UNPROTECTED,
                       K.DETAIL_TRANSCRIPTS_GONE_UNPROTECTED_MORE, {"count": count, "samples": samples, "more": more})
    return Verdict(K.KEY_TRANSCRIPTS_GONE_UNPROTECTED, FIRING, "error", K.TITLE_TRANSCRIPTS_GONE_UNPROTECTED,
                   K.DETAIL_TRANSCRIPTS_GONE_UNPROTECTED, {"count": count, "samples": samples})
