
from __future__ import annotations

from typing import Dict, Hashable, Optional, Set, Tuple


class TerminalSizeNegotiator:

    def __init__(self) -> None:
        self._sizes: Dict[str, Dict[Hashable, Tuple[int, int]]] = {}
        self._withdrawn: Dict[str, Set[Hashable]] = {}
        self._last: Dict[str, Tuple[int, int]] = {}
        self._client_ids: Dict[str, Dict[Hashable, str]] = {}
        self._masters: Dict[str, str] = {}

    def bind_client_id(
        self, session_id: str, client_key: Hashable, client_id: Optional[str]
    ) -> None:
        if client_id:
            self._client_ids.setdefault(session_id, {})[client_key] = client_id

    def set_master(
        self, session_id: str, client_id: Optional[str]
    ) -> Optional[Tuple[int, int]]:
        before = self.effective_size(session_id)
        if client_id:
            self._masters[session_id] = client_id
        else:
            self._masters.pop(session_id, None)
        after = self.effective_size(session_id)
        return None if after == before else after

    def master(self, session_id: str) -> Optional[str]:
        return self._masters.get(session_id)

    def master_attached(self, session_id: str) -> bool:
        master = self._masters.get(session_id)
        ids = self._client_ids.get(session_id, {})
        return master is not None and master in ids.values()

    def set_client_size(
        self,
        session_id: str,
        client_key: Hashable,
        cols: int,
        rows: int,
        voting: bool = True,
    ) -> Optional[Tuple[int, int]]:
        if cols <= 0 or rows <= 0:
            return None

        before = self.effective_size(session_id)
        clients = self._sizes.setdefault(session_id, {})
        clients[client_key] = (cols, rows)
        withdrawn = self._withdrawn.setdefault(session_id, set())
        if voting:
            withdrawn.discard(client_key)
        else:
            withdrawn.add(client_key)
        after = self.effective_size(session_id)

        if after == before:
            return None
        return after

    def remove_client(
        self, session_id: str, client_key: Hashable
    ) -> Optional[Tuple[int, int]]:
        ids = self._client_ids.get(session_id)
        if ids is not None:
            ids.pop(client_key, None)
            if not ids:
                del self._client_ids[session_id]
        clients = self._sizes.get(session_id)
        if not clients or client_key not in clients:
            return None

        before = self.effective_size(session_id)
        del clients[client_key]
        self._withdrawn.get(session_id, set()).discard(client_key)
        if not clients:
            del self._sizes[session_id]
            self._withdrawn.pop(session_id, None)
            self._last.pop(session_id, None)
            return None

        after = self.effective_size(session_id)
        if after == before:
            return None
        return after

    def effective_size(self, session_id: str) -> Optional[Tuple[int, int]]:
        clients = self._sizes.get(session_id)
        if not clients:
            return None
        withdrawn = self._withdrawn.get(session_id, set())
        master = self._masters.get(session_id)
        ids = self._client_ids.get(session_id, {})
        sizes = [
            size for key, size in clients.items()
            if key not in withdrawn and (master is None or ids.get(key) == master)
        ]
        if not sizes:
            return self._last.get(session_id)
        cols = min(c for c, _ in sizes)
        rows = min(r for _, r in sizes)
        self._last[session_id] = (cols, rows)
        return (cols, rows)

    def voter_count(self, session_id: str) -> int:
        clients = self._sizes.get(session_id)
        if not clients:
            return 0
        withdrawn = self._withdrawn.get(session_id, set())
        master = self._masters.get(session_id)
        ids = self._client_ids.get(session_id, {})
        return sum(
            1 for key in clients
            if key not in withdrawn and (master is None or ids.get(key) == master)
        )

    def note_pane_size(self, session_id: str, cols: int, rows: int) -> bool:
        if cols <= 0 or rows <= 0 or session_id not in self._sizes:
            return False
        if self.effective_size(session_id) is not None:
            return False
        self._last[session_id] = (cols, rows)
        return True

    def client_count(self, session_id: str) -> int:
        clients = self._sizes.get(session_id)
        return len(clients) if clients else 0
