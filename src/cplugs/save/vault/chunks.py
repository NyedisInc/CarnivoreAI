
from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Callable, Iterator, Optional, Set, Tuple

from src.cplugs.save.engine import layout
from src.cplugs.save.vault import constants as K
from src.cplugs.sdk.blob_codec import (
    BLOB_EXTENSIONS,
    BlobCorrupt,
    BlobMissing,
    ChunkRef,
    blob_relpath,
    compress,
    decompress,
    default_codec,
)


class BlobStore:

    def __init__(self, root: Path, codec: Optional[str] = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._root = Path(root)
        self._dir = self._root / K.BLOBS_DIR
        self._codec = codec or default_codec()
        self.new_blobs = 0
        self.new_bytes = 0
        self._lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._dirty: set = set()
        self._clock = clock
        self._known: Set[str] = set()
        self._known_until = clock() + K.CHUNK_KNOWN_SECONDS
        self._folder_id = self._identity()

    def _identity(self) -> Optional[Tuple[int, int]]:
        try:
            st = os.stat(self._dir)
        except OSError:
            return None
        return st.st_dev, st.st_ino

    def revalidate(self) -> None:
        now = self._identity()
        with self._lock:
            if now != self._folder_id:
                self._folder_id = now
                self._known = set()

    def _path(self, sha: str, codec: str) -> Path:
        return self._root / blob_relpath(sha, codec)

    def find(self, sha: str) -> Optional[Tuple[Path, str]]:
        for codec in BLOB_EXTENSIONS:
            path = self._path(sha, codec)
            if path.is_file():
                return path, codec
        return None

    def has(self, sha: str) -> bool:
        with self._lock:
            self._roll_window()
            if sha in self._known:
                return True
        found = self.find(sha) is not None
        if found:
            self._remember(sha)
        return found

    def _roll_window(self) -> None:
        now = self._clock()
        if now >= self._known_until:
            self._known = set()
            self._known_until = now + K.CHUNK_KNOWN_SECONDS

    def _remember(self, sha: str) -> None:
        with self._lock:
            self._roll_window()
            if self._folder_id is None:
                self._folder_id = self._identity()
            if len(self._known) >= K.CHUNK_KNOWN_MAX:
                self._known = set()
            self._known.add(sha)

    def forget(self, sha: str) -> None:
        with self._lock:
            self._known.discard(sha)

    def on_disk(self, sha: str) -> bool:
        found = self.find(sha) is not None
        if found:
            self._remember(sha)
        else:
            self.forget(sha)
        return found

    def remove(self, sha: str, *, path: Optional[Path] = None, prune: bool = False) -> int:
        paths = [path] if path is not None else [p for codec in BLOB_EXTENSIONS if (p := self._path(sha, codec)).is_file()]
        freed = 0
        try:
            for victim in paths:
                try:
                    freed += victim.stat().st_size
                except OSError:
                    pass
                victim.unlink(missing_ok=True)
        finally:
            self.forget(sha)
        if prune and paths:
            folder = paths[0].parent
            try:
                folder.rmdir()
                with self._lock:
                    self._dirty.discard(folder)
            except OSError:
                pass
        return freed

    def put(self, raw: bytes) -> Tuple[ChunkRef, int, bool]:
        ref = ChunkRef(hashlib.sha256(raw).hexdigest(), len(raw))
        found = self.find(ref.sha256)
        if found is not None:
            self._remember(ref.sha256)
            return ref, self._touch(found[0]), False
        packed = compress(raw, self._codec)
        dest = self._path(ref.sha256, self._codec)
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(f".tmp-{os.getpid()}-{threading.get_ident()}-{ref.sha256[:12]}")
        try:
            with open(temp, "wb") as handle:
                handle.write(packed)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, dest)
        finally:
            temp.unlink(missing_ok=True)
        with self._lock:
            self.new_blobs += 1
            self.new_bytes += len(packed)
            self._dirty.add(dest.parent)
        self._remember(ref.sha256)
        return ref, len(packed), True

    def _touch(self, path: Path) -> int:
        try:
            st = path.stat()
            if time.time() - st.st_mtime > K.BLOB_TOUCH_SECONDS:
                os.utime(path, None)
            return st.st_size
        except OSError:
            return 0

    def sync_dirs(self) -> None:
        with self._sync_lock:
            with self._lock:
                folders, self._dirty = self._dirty, set()
            try:
                for folder in folders:
                    layout.fsync_path(folder)
                if folders:
                    layout.fsync_path(self._dir)
            except OSError:
                with self._lock:
                    self._dirty |= folders
                raise

    def get(self, ref: ChunkRef) -> bytes:
        found = self.find(ref.sha256)
        if found is None:
            raise BlobMissing(f"chunk {ref.sha256[:12]} is not in the vault")
        path, codec = found
        raw = decompress(path.read_bytes(), codec)
        if hashlib.sha256(raw).hexdigest() != ref.sha256 or len(raw) != ref.length:
            raise BlobCorrupt(f"chunk {ref.sha256[:12]} does not match its name")
        return raw

    def stored_size(self, sha: str) -> int:
        found = self.find(sha)
        try:
            return found[0].stat().st_size if found else 0
        except OSError:
            return 0

    def all_blobs(self) -> Iterator[Tuple[str, Path]]:
        if not self._dir.is_dir():
            return
        for sub in self._dir.iterdir():
            if not sub.is_dir():
                continue
            for entry in sub.iterdir():
                if entry.name.startswith("."):
                    continue
                yield entry.stem, entry

    def temp_files(self) -> Iterator[Path]:
        if not self._dir.is_dir():
            return
        for sub in self._dir.iterdir():
            if sub.is_dir():
                yield from (entry for entry in sub.iterdir() if entry.name.startswith(".tmp-"))
