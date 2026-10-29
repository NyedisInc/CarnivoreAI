
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.units import peek_working_dir


class WorkingDirMemo:

    def __init__(self, max_files: int = K.WORKDIR_MEMO_MAX) -> None:
        self._max = max_files
        self._lock = threading.Lock()
        self._found: Dict[str, Tuple[int, int, int, str]] = {}

    def get(self, path: Optional[Path]) -> Optional[str]:
        if path is None:
            return None
        key = str(path)
        try:
            st = os.stat(path)
        except OSError:
            return None
        with self._lock:
            known = self._found.get(key)
        if known is not None and known[0] == st.st_dev and known[1] == st.st_ino and st.st_size >= known[2]:
            return known[3]
        found = peek_working_dir(path)
        if found is not None:
            with self._lock:
                if len(self._found) >= self._max:
                    self._found = {}
                self._found[key] = (st.st_dev, st.st_ino, st.st_size, found)
        return found
