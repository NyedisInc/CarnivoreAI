
from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Iterator, Optional, Tuple

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

    def __init__(self, root: Path, codec: Optional[str] = None) -> None:
        self._root = Path(root)
        self._dir = self._root / K.BLOBS_DIR
        self._codec = codec or default_codec()
        self.new_blobs = 0
        self.new_bytes = 0
        self._lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._dirty: set = set()

    def _path(self, sha: str, codec: str) -> Path:
        return self._root / blob_relpath(sha, codec)

    def find(self, sha: str) -> Optional[Tuple[Path, str]]:
        for codec in BLOB_EXTENSIONS:
            path = self._path(sha, codec)
            if path.is_file():
                return path, codec
        return None

    def has(self, sha: str) -> bool:
        return self.find(sha) is not None

    def put(self, raw: bytes) -> Tuple[ChunkRef, int, bool]:
        ref = ChunkRef(hashlib.sha256(raw).hexdigest(), len(raw))
        found = self.find(ref.sha256)
        if found is not None:
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
