
from __future__ import annotations

import hashlib
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core.approvals.bounds import fit_text
from src.core.attention.startup_screen import StartupScreen, shown_screen

logger = structlog.get_logger()

SOURCE_STARTUP_PROMPT: str = "startup_prompt"
STARTUP_BODY_MAX: int = 4000


def startup_item_id(session_id: str, instance: Any, kind: str) -> str:
    digest = hashlib.sha256(f"{instance!r}|{kind}".encode("utf-8")).hexdigest()
    return f"sp:{session_id}:{digest[:16]}"


def _fingerprint(screen: StartupScreen) -> str:
    return hashlib.sha256(f"{screen.kind}\n{screen.text}".encode("utf-8")).hexdigest()


class StartupPromptProvider:

    def __init__(
        self, get_watcher: Callable[[], Any], get_manager: Callable[[], Any],
        on_first_seen: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self._watcher = get_watcher
        self._manager = get_manager
        self._on_first_seen = on_first_seen
        self._first_seen: Dict[str, str] = {}

    def _open(self) -> List[Tuple[str, StartupScreen, Any, Optional[str]]]:
        watcher = self._watcher()
        if watcher is None:
            return []
        found = []
        for session_id in watcher.observed_session_ids():
            if str(session_id).startswith("remote:"):
                continue
            observation = watcher.observation_for(session_id)
            screen = shown_screen(observation)
            if screen is None or observation.evidence.dialog is not None:
                continue
            identity = observation.evidence.identity or ()
            found.append((session_id, screen, tuple(identity[:4]), observation.evidence.agent_family))
        return found

    def signature(self) -> frozenset:
        current = self._open()
        out = set()
        live: Set[str] = set()
        for session_id, screen, instance, _family in current:
            item = startup_item_id(session_id, instance, screen.kind)
            live.add(item)
            if item not in self._first_seen:
                self._first_seen[item] = screen.since.isoformat()
                self._announce(session_id, item, screen)
            out.add((SOURCE_STARTUP_PROMPT, item, _fingerprint(screen)))
        for gone in set(self._first_seen) - live:
            del self._first_seen[gone]
        return frozenset(out)

    def _announce(self, session_id: str, item: str, screen: StartupScreen) -> None:
        if self._on_first_seen is None:
            return
        try:
            self._on_first_seen({"id": item, "session_id": session_id, "kind": screen.kind,
                                 "matched": screen.matched, "body": screen.text})
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("startup_prompt_first_seen_failed", error_type=type(exc).__name__)

    async def items(self) -> List[Dict[str, Any]]:
        manager = self._manager()
        out: List[Dict[str, Any]] = []
        if manager is None:
            return out
        self.signature()
        for session_id, screen, instance, family in self._open():
            info = await manager.get_session_info(session_id)
            if info is None or str(info.session.id).startswith("remote:"):
                continue
            item = startup_item_id(session_id, instance, screen.kind)
            out.append({
                "id": item, "source": SOURCE_STARTUP_PROMPT, "host": "local",
                "session_id": info.session.id, "session_name": info.label or info.tmux_session,
                "tmux_session": info.tmux_session, "project": info.project_name,
                "family": family, "kind": screen.kind,
                "question": "", "body": fit_text(screen.text, STARTUP_BODY_MAX), "options": [], "rows": [],
                "fingerprint": _fingerprint(screen), "created_at": self._first_seen.get(item),
            })
        return out


def journal_writer(get_state_dir: Callable[[], Any], get_watcher: Callable[[], Any]) -> Callable[[Dict[str, Any]], None]:
    from src.core import session_journal_store as store

    def write(item: Dict[str, Any]) -> None:
        watcher = get_watcher()
        observation = watcher.observation_for(item["session_id"]) if watcher is not None else None
        identity = getattr(getattr(observation, "evidence", None), "identity", None) or ()
        name = identity[1] if len(identity) > 1 else item["session_id"]
        how = "marker" if item.get("matched") else "fallback"
        store.append_human_log(
            get_state_dir(), "startup_prompt_seen",
            f"session={name} kind={item['kind']} via={how} screen={item['body']}",
        )

    return write
