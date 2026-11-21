
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, List, Optional

KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
MAX_VALUE_BYTES = 256 * 1024
MAX_KEYS = 1000
MAX_TOTAL_BYTES = 4 * 1024 * 1024


class StorageRefused(Exception):

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class HostStorage:

    def __init__(self, data_dir: Path) -> None:
        self._path = Path(data_dir) / "host.db"
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path), timeout=5)

    @staticmethod
    def _key(key: object) -> str:
        if not isinstance(key, str) or not KEY.match(key):
            raise StorageRefused("invalid_params", "key must match [A-Za-z0-9_.:-]{1,128}")
        return key

    def get(self, key: object) -> Optional[Any]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT v FROM kv WHERE k = ?", (self._key(key),)).fetchone()
        return None if row is None else json.loads(row[0])

    def put(self, key: object, value: Any) -> None:
        text = json.dumps(value, separators=(",", ":"))
        if len(text.encode("utf-8")) > MAX_VALUE_BYTES:
            raise StorageRefused("too_large", f"a value is at most {MAX_VALUE_BYTES} bytes")
        with closing(self._connect()) as conn:
            k = self._key(key)
            count, total = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(LENGTH(v)), 0) FROM kv WHERE k != ?", (k,)).fetchone()
            if count >= MAX_KEYS or total + len(text) > MAX_TOTAL_BYTES:
                raise StorageRefused("too_large", "storage quota reached")
            conn.execute("INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (k, text))
            conn.commit()

    def delete(self, key: object) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM kv WHERE k = ?", (self._key(key),))
            conn.commit()

    def list(self, prefix: str = "") -> List[str]:
        if not isinstance(prefix, str) or len(prefix) > 128:
            raise StorageRefused("invalid_params", "prefix")
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT k FROM kv ORDER BY k").fetchall()
        return [r[0] for r in rows if r[0].startswith(prefix)][:MAX_KEYS]
