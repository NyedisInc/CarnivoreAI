
from __future__ import annotations

import hashlib
import tarfile
from typing import Callable, Dict, Iterable, List, Optional

from src.core.project_pack import archive_io, inventory
from src.core.project_pack import constants as K
from src.core.project_pack.inventory import Entry

MAX_REPORTED = 10


class VerifyError(Exception):
    pass


def _kind_of(member: tarfile.TarInfo) -> Optional[str]:
    if member.isdir():
        return inventory.KIND_DIR
    if member.issym():
        return inventory.KIND_LINK
    if member.isreg() or member.islnk():
        return inventory.KIND_FILE
    return None


def compare(expected: Dict[str, Entry], actual: Dict[str, Entry], links: Optional[Dict[str, str]] = None) -> List[str]:
    links = links or {}
    problems: List[str] = []
    for path in sorted(expected.keys() - actual.keys()):
        problems.append(f"missing: {path}")
    for path in sorted(actual.keys() - expected.keys()):
        problems.append(f"unexpected: {path}")
    for path in sorted(expected.keys() & actual.keys()):
        want, got = expected[path], actual[path]
        if want.kind != got.kind:
            problems.append(f"type differs: {path}")
        elif want.kind != inventory.KIND_LINK and want.mode != got.mode:
            problems.append(f"mode differs: {path} ({want.mode:o} vs {got.mode:o})")
        elif want.kind == inventory.KIND_LINK and want.link != got.link:
            problems.append(f"symlink target differs: {path}")
        elif want.kind == inventory.KIND_FILE:
            if path in links:
                target = expected.get(links[path])
                if target is None or target.group is None or target.group != want.group:
                    problems.append(f"hard link differs: {path}")
            elif want.size != got.size or want.sha256 != got.sha256:
                problems.append(f"content differs: {path}")
    return problems


def _raise(problems: List[str]) -> None:
    more = f" (and {len(problems) - MAX_REPORTED} more)" if len(problems) > MAX_REPORTED else ""
    raise VerifyError("; ".join(problems[:MAX_REPORTED]) + more)


def read_archive(archive: str, progress: Optional[Callable[[int], None]] = None) -> tuple:
    actual: Dict[str, Entry] = {}
    links: Dict[str, str] = {}
    proc = archive_io.open_plain_tar_stream(archive)
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                path = member.name.rstrip("/")
                kind = _kind_of(member)
                if kind is None:
                    raise VerifyError(f"unsupported member type in the archive: {path}")
                entry = Entry(path, kind, size=0, mode=member.mode & 0o7777, link=member.linkname if member.issym() else None)
                if member.islnk():
                    links[path] = member.linkname.rstrip("/")
                elif member.isreg():
                    entry.size = member.size
                    entry.sha256 = _hash_member(tar.extractfile(member), progress)
                actual[path] = entry
    except tarfile.TarError as exc:
        raise VerifyError(f"the archive does not decode as tar: {exc}") from exc
    finally:
        archive_io.finish_stream(proc)
    return actual, links


def _hash_member(handle, progress: Optional[Callable[[int], None]]) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(K.HASH_CHUNK), b""):
        digest.update(chunk)
        if progress:
            progress(len(chunk))
    return digest.hexdigest()


def verify_archive(archive: str, manifest_entries: Iterable[Entry], progress: Optional[Callable[[int], None]] = None) -> None:
    expected = {e.path: e for e in manifest_entries}
    actual, links = read_archive(archive, progress)
    problems = compare(expected, actual, links)
    if problems:
        _raise(problems)


def verify_tree(root: str, manifest_entries: Iterable[Entry], progress: Optional[Callable[[int], None]] = None,
                skip_top: Iterable[str] = ()) -> None:
    expected = {e.path: e for e in manifest_entries}
    tree = inventory.walk(root, skip_top)
    inventory.hash_files(root, tree.entries, progress)
    problems = compare(expected, {e.path: e for e in tree.entries})
    if problems:
        _raise(problems)
