
from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import unicodedata
from pathlib import Path
from typing import IO, List, Optional, Sequence

import structlog

from src.config import settings

logger = structlog.get_logger()

EXCLUDE_ANYWHERE = ("node_modules", ".venv", "venv", "__pycache__", ".git")
EXCLUDE_TOP = ("^./.next", "^./dist", "^./.gitmodules")
MAX_EXTRACT_BYTES = 64 * 1024 ** 3
MAX_MEMBERS = 500_000
FREE_MARGIN_BYTES = 2 * 1024 ** 3
_ZSTD_CANDIDATES = ("/opt/homebrew/bin/zstd", "/usr/local/bin/zstd", "/usr/bin/zstd")


class TarballError(Exception):
    """The archive could not be made or unpacked; ``code`` is the stable reason, the message never names a file's content."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


def _zstd() -> str:
    found = shutil.which("zstd") or next((p for p in _ZSTD_CANDIDATES if os.access(p, os.X_OK)), None)
    if found is None:
        raise TarballError("zstd_missing", "zstd is not installed on this computer")
    return found


def _env() -> dict:
    return {**os.environ, "COPYFILE_DISABLE": "1"}


def make_tarball(root: str, dest: str, *, extra_excludes: Sequence[str] = (), members: Optional[Sequence[str]] = None) -> int:
    if not os.path.isdir(root):
        raise TarballError("not_a_folder", "the project folder is not there")
    argv = ["tar", "-C", root, "-cf", "-"]
    for name in (*EXCLUDE_ANYWHERE, *EXCLUDE_TOP, *extra_excludes):
        argv += ["--exclude", name]
    listing = None
    if members is None:
        argv.append(".")
    else:
        handle, listing = tempfile.mkstemp(prefix="members-")
        with os.fdopen(handle, "w") as out:
            out.write("\n".join(members) + "\n")
        argv += ["-T", listing]
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            tar = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env())
            zst = subprocess.run([_zstd(), "-q", "-T0", "-3"], stdin=tar.stdout, stdout=out, stderr=subprocess.PIPE, check=False)
            tar.stdout.close()
            tar_err = tar.stderr.read()
            if tar.wait() != 0 or zst.returncode != 0:
                logger.warning("pack_tarball_failed", tar_status=tar.returncode, zstd_status=zst.returncode, stderr_bytes=len(tar_err))
                raise TarballError("tar_failed", "the archive could not be made")
    except BaseException:
        Path(dest).unlink(missing_ok=True)
        raise
    finally:
        if listing:
            Path(listing).unlink(missing_ok=True)
    return os.path.getsize(dest)


def list_members(archive: str) -> List[str]:
    zst = subprocess.Popen([_zstd(), "-dc", "-q", archive], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tar = subprocess.run(["tar", "-tf", "-"], stdin=zst.stdout, capture_output=True, check=False)
    zst.stdout.close()
    if zst.wait() != 0 or tar.returncode != 0:
        raise TarballError("tar_failed", "the archive cannot be read")
    return [ln for ln in tar.stdout.decode("utf-8", "replace").splitlines() if ln]


def _norm_component(part: str) -> str:
    return unicodedata.normalize("NFC", part).casefold().rstrip(". ")


def unsafe_member(name: str) -> bool:
    parts = Path(name).parts
    if name.startswith("/") or ".." in parts or any(_norm_component(p) == ".git" for p in parts):
        return True
    clean = [p for p in parts if p != "."]
    return bool(clean) and _norm_component(clean[0]) == ".gitmodules"


def _refuse_member(m: tarfile.TarInfo) -> Optional[str]:
    if unsafe_member(m.name):
        return "the archive names a path outside the folder or a git control path"
    if m.islnk():
        return "the archive holds a hard link"
    if m.issym():
        if m.linkname.startswith("/") or ".." in Path(m.linkname).parts or unsafe_member(m.linkname):
            return "the archive holds a link that leaves the folder"
        return None
    if not (m.isreg() or m.isdir()):
        return "the archive holds a device or special file"
    return None


def _through_link(dest: str, name: str, *, is_link: bool) -> bool:
    parts = [p for p in Path(name).parts if p != "."]
    walk = dest
    for index, part in enumerate(parts):
        walk = os.path.join(walk, part)
        if index == len(parts) - 1 and is_link:
            return False
        if os.path.islink(walk):
            return True
    return False


class _CountingReader:

    def __init__(self, raw: IO[bytes], limit: int) -> None:
        self.raw, self.limit, self.seen = raw, limit, 0

    def read(self, n: int = -1) -> bytes:
        data = self.raw.read(n)
        self.seen += len(data)
        if self.seen > self.limit:
            raise TarballError("unsafe_archive", "the archive expands past the size this computer allows")
        return data


def _ceiling(dest: str, max_bytes: Optional[int]) -> int:
    if max_bytes is not None:
        return max_bytes
    free = []
    for probe in (dest, str(settings.get_state_dir())):
        while not os.path.exists(probe) and os.path.dirname(probe) != probe:
            probe = os.path.dirname(probe)
        free.append(shutil.disk_usage(probe).free)
    return max(0, min(MAX_EXTRACT_BYTES, min(free) - FREE_MARGIN_BYTES))


def extract_tarball(archive: str, dest: str, *, max_bytes: Optional[int] = None, max_members: int = MAX_MEMBERS) -> int:
    if os.path.isdir(dest) and os.listdir(dest):
        raise TarballError("dest_not_empty", "the target folder already holds files")
    limit = _ceiling(dest, max_bytes)
    made = not os.path.isdir(dest)
    os.makedirs(dest, exist_ok=True)
    zst = subprocess.Popen([_zstd(), "-dc", "-q", archive], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    count = 0
    try:
        with tarfile.open(fileobj=_CountingReader(zst.stdout, limit), mode="r|") as tar:
            for m in tar:
                count += 1
                reason = _refuse_member(m) if count <= max_members else "the archive holds too many files"
                if reason:
                    raise TarballError("unsafe_archive", reason)
                if _through_link(dest, m.name, is_link=m.issym()):
                    raise TarballError("unsafe_archive", "the archive writes through a link")
                tar.extract(m, dest, set_attrs=False, filter="data")
    except (tarfile.TarError, OSError, ValueError) as exc:
        _clean(dest, made)
        raise TarballError("tar_failed", "the archive could not be unpacked") from exc
    except TarballError:
        _clean(dest, made)
        raise
    finally:
        zst.stdout.close()
        if zst.poll() is None:
            zst.kill()
        zst.wait()
    if zst.returncode not in (0, -9):
        _clean(dest, made)
        raise TarballError("tar_failed", "the archive could not be unpacked")
    return count


def _clean(dest: str, made: bool) -> None:
    if made:
        shutil.rmtree(dest, ignore_errors=True)
        return
    for entry in os.listdir(dest):
        path = os.path.join(dest, entry)
        shutil.rmtree(path, ignore_errors=True) if os.path.isdir(path) and not os.path.islink(path) else os.unlink(path)


def install_commands(root: str) -> List[List[str]]:
    has = lambda name: os.path.isfile(os.path.join(root, name))  # noqa: E731
    out: List[List[str]] = []
    if has("package-lock.json"):
        out.append(["npm", "ci"])
    elif has("pnpm-lock.yaml"):
        out.append(["pnpm", "install", "--frozen-lockfile"])
    elif has("yarn.lock"):
        out.append(["yarn", "install", "--frozen-lockfile"])
    elif has("package.json"):
        out.append(["npm", "install"])
    if has("requirements.txt"):
        out += [["python3", "-m", "venv", ".venv"], [".venv/bin/pip", "install", "-r", "requirements.txt"]]
    return out
