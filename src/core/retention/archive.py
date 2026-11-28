
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import structlog

from src.core.retention import constants as K
from src.core.retention.errors import ArchiveError, ToolMissingError

logger = structlog.get_logger()


def find_tool(name: str) -> str:
    found = shutil.which(name, path=os.pathsep.join([os.environ.get("PATH", ""), *K.EXTRA_TOOL_DIRS]))
    if found is None:
        raise ToolMissingError(f"{name} not found")
    return found


def count_entries(bundle: Path) -> int:
    total = 1
    for _root, dirs, files in os.walk(bundle, followlinks=False):
        total += len(dirs) + len(files)
    return total


def count_archive_entries(archive: Path) -> int:
    zstd, tar = find_tool("zstd"), find_tool("tar")
    with subprocess.Popen([zstd, "-dc", str(archive)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as dec:
        listing = subprocess.run([tar, "-t", "-f", "-"], stdin=dec.stdout, capture_output=True, timeout=K.PACK_TIMEOUT_SECONDS, check=False)
        if dec.stdout is not None:
            dec.stdout.close()
        dec.wait(timeout=K.PACK_TIMEOUT_SECONDS)
    if dec.returncode != 0 or listing.returncode != 0:
        raise ArchiveError(f"{archive.name} did not read back (zstd {dec.returncode}, tar {listing.returncode})")
    return len(listing.stdout.splitlines())


def archive_matches(archive: Path, bundle: Path) -> bool:
    try:
        return count_archive_entries(archive) == count_entries(bundle)
    except (ArchiveError, subprocess.SubprocessError, OSError) as exc:
        logger.warning("retention_archive_unreadable", archive=str(archive), error=str(exc))
        return False


def pack_bundle(bundle: Path, out: Path) -> Path:
    tar, zstd = find_tool("tar"), find_tool("zstd")
    out.parent.mkdir(parents=True, exist_ok=True)
    partial: Optional[Path] = out.with_name(out.name + K.PARTIAL_SUFFIX)
    try:
        with subprocess.Popen([tar, "-c", "-f", "-", "-C", str(bundle.parent), bundle.name], stdout=subprocess.PIPE) as packer:
            made = subprocess.run([zstd, "-q", "-T0", "-3", "-f", "-o", str(partial)], stdin=packer.stdout,
                                  capture_output=True, timeout=K.PACK_TIMEOUT_SECONDS, check=False)
            if packer.stdout is not None:
                packer.stdout.close()
            packer.wait(timeout=K.PACK_TIMEOUT_SECONDS)
        if packer.returncode != 0 or made.returncode != 0:
            raise ArchiveError(f"packing {bundle.name} failed (tar {packer.returncode}, zstd {made.returncode})")
        if not archive_matches(partial, bundle):
            raise ArchiveError(f"{bundle.name} packed with a different entry count than the bundle")
        os.replace(partial, out)
        partial = None
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArchiveError(f"packing {bundle.name} failed: {exc}") from exc
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)
    return out
