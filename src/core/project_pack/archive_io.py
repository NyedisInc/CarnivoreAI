
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import IO, List, Sequence

import structlog

from src.core.project_pack import constants as K

logger = structlog.get_logger()


class ArchiveToolError(Exception):
    pass


def zstd_threads() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def create_command(root: str, names: Sequence[str], out_path: str, level: int, threads: int) -> List[str]:
    options = f"zstd:compression-level={level},zstd:threads={threads},zstd:long={K.ZSTD_LONG_WINDOW}"
    return [K.NICE_BIN, "-n", str(K.NICE_LEVEL), K.TAR_BIN, "--no-mac-metadata", "--format", "pax", "--zstd",
            "--options", options, "-cf", out_path, "-C", root, "--", *names]


def run_checked(command: Sequence[str], what: str) -> None:
    try:
        done = subprocess.run(list(command), capture_output=True, text=True, check=False)
    except OSError as exc:
        raise ArchiveToolError(f"{what}: cannot run {command[0]}: {exc}") from exc
    if done.returncode != 0:
        raise ArchiveToolError(f"{what} failed (exit {done.returncode}): {done.stderr.strip()[:500]}")


def create_archive(root: str, names: Sequence[str], out_path: str, level: int = K.COMPRESSION_LEVEL,
                   threads: int = 0) -> None:
    run_checked(create_command(root, names, out_path, level, threads or zstd_threads()), "tar create")


def extract_archive(archive: str, dest: str) -> None:
    run_checked([K.NICE_BIN, "-n", str(K.NICE_LEVEL), K.TAR_BIN, "-xpf", archive, "-C", dest], "tar extract")


def open_plain_tar_stream(archive: str) -> subprocess.Popen:
    return subprocess.Popen([K.TAR_BIN, "-cf", "-", f"@{archive}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def finish_stream(proc: subprocess.Popen) -> None:
    stdout: IO[bytes] = proc.stdout  # type: ignore[assignment]
    while stdout.read(K.HASH_CHUNK):
        pass
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    code = proc.wait()
    if code != 0:
        raise ArchiveToolError(f"tar could not decode the archive (exit {code}): {err.strip()[:500]}")


def probe_works() -> str:
    with tempfile.TemporaryDirectory(prefix="carnivore-pack-probe-") as work:
        (Path(work) / "probe.txt").write_text("probe")
        out = str(Path(work) / "probe.tar.zst")
        try:
            run_checked(create_command(work, ["probe.txt"], out, 1, 1), "tar probe")
            run_checked([K.TAR_BIN, "-tf", out], "tar probe read")
        except (ArchiveToolError, OSError) as exc:
            return str(exc)
    return ""
