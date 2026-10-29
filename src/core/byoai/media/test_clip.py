"""A short spoken test clip for every transcribe-capable adapter's ``test()`` (D15).

Made at test time with macOS ``say`` and ``afconvert`` (16 kHz mono 16-bit WAV)
and cached under the state directory, so no audio file lives in the repo. When
``say`` or ``afconvert`` is missing (not a Mac), :func:`get_test_clip` answers
None and the adapter's test reports "could not test" (not ok): a check that sent
nothing to the provider never reads as a pass.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

CLIP_TEXT = "carnivore connection test"
CLIP_NAME = "byoai-test-clip.wav"
_TIMEOUT_S = 20.0


def _cache_path(state_dir: Optional[Path]) -> Path:
    """Where the clip is cached: ``<state_dir>/byoai-test-clip.wav``.

    Inputs: state_dir (Path | None) - None means the app's state directory.
    Example: _cache_path(Path("/tmp/s")) -> Path("/tmp/s/byoai-test-clip.wav")
    """
    if state_dir is None:
        from src.config import settings
        state_dir = settings.get_state_dir()
    return Path(state_dir) / CLIP_NAME


async def _run(*argv: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        return await asyncio.wait_for(proc.wait(), _TIMEOUT_S) == 0
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        log.warning("byoai_test_clip_timeout", tool=argv[0])
        return False


async def get_test_clip(state_dir: Optional[Path] = None) -> Optional[bytes]:
    say, afconvert = shutil.which("say"), shutil.which("afconvert")
    if not say or not afconvert:
        return None
    path = _cache_path(state_dir)
    if path.is_file() and path.stat().st_size > 44:
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="byoai-clip-") as tmp:
        aiff, wav = Path(tmp) / "clip.aiff", Path(tmp) / "clip.wav"
        if not await _run(say, "-o", str(aiff), CLIP_TEXT):
            return None
        if not await _run(afconvert, "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(wav)):
            return None
        data = wav.read_bytes()
        path.write_bytes(data)
    return data
