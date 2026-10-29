
from __future__ import annotations

import hmac
import json
import secrets
from pathlib import Path
from typing import Callable, Optional

import structlog

from src.core.hook_token_recovery import SupersededHookTokens

logger = structlog.get_logger()

TOKEN_BYTES = 32

_DUMMY_TOKEN = secrets.token_urlsafe(TOKEN_BYTES)

# state directory
METADATA_FILENAME = "session_metadata.json"

OWNED_KEY = "owned_tmux_sessions"


class HookTokenAuthority:

    def __init__(
        self,
        state_dir: Callable[[], Path],
        *,
        on_drop: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._state_dir = state_dir
        self._on_drop = on_drop
        self.tokens: dict[str, str] = {}
        self.tmux_names: dict[str, str] = {}
        self.durable: bool = True
        self.superseded = SupersededHookTokens()
        self.load()


    def load(self) -> None:
        try:
            from src.core.hook_tokens import load_tokens

            result = load_tokens(self._state_dir())
            self.tokens = dict(result.tokens)
            self.tmux_names = dict(result.tmux_names)
            self.gc()
            self.durable = result.durable
            if not result.durable:
                logger.warning(
                    "hook_tokens_not_durable",
                    detail=result.detail,
                    note=(
                        "sessions that survive a restart will 403 on every "
                        "hook until they are recreated"
                    ),
                )
            elif result.tokens:
                logger.info("hook_tokens_restored", count=len(result.tokens))
        except Exception as exc:  # noqa: BLE001
            self.tokens = {}
            self.tmux_names = {}
            self.durable = False
            logger.warning("hook_tokens_load_threw", error=str(exc))

    def persist(self) -> None:
        try:
            from src.core.hook_tokens import save_tokens

            ok, reason = save_tokens(
                self._state_dir(), self.tokens, tmux_names=self.tmux_names
            )
            self.durable = ok
            if not ok:
                logger.warning("hook_tokens_not_persisted", reason=reason)
        except Exception as exc:  # noqa: BLE001
            self.durable = False
            logger.warning("hook_tokens_persist_threw", error=str(exc))

    def gc(self) -> list[str]:
        if not self.tokens:
            return []
        try:
            meta = self._state_dir() / METADATA_FILENAME
            if not meta.exists():
                return []
            owned = set(json.loads(meta.read_text()).get(OWNED_KEY) or [])
        except (OSError, ValueError) as exc:
            logger.debug("hook_token_gc_skipped", error=str(exc))
            return []
        if not owned:
            return []

        dead = [sid for sid, name in self.tmux_names.items() if name not in owned]
        if not dead:
            return []
        for sid in dead:
            self._drop(sid)
        logger.info("hook_tokens_gc", dropped=len(dead))
        self.persist()
        return dead

    def _drop(self, session_id: str) -> None:
        self.tokens.pop(session_id, None)
        self.tmux_names.pop(session_id, None)
        self.superseded.forget(session_id)
        if self._on_drop is not None:
            self._on_drop(session_id)

    def release(self, session_id: str, *, tmux_name: str) -> bool:
        if self.tmux_names.get(session_id) != tmux_name:
            return False
        self._drop(session_id)
        logger.info(
            "hook_token_released_for_gone_instance",
            session_id=session_id,
            tmux_name=tmux_name,
        )
        self.persist()
        return True


    def mint(self, session_id: str, tmux_name: Optional[str] = None) -> str:
        previous = self.tokens.get(session_id)
        if previous:
            self.superseded.record(
                session_id,
                previous,
                tmux_name=(self.tmux_names.get(session_id) or tmux_name),
            )
        token = secrets.token_urlsafe(TOKEN_BYTES)
        self.tokens[session_id] = token
        if tmux_name:
            self.tmux_names[session_id] = tmux_name
        self.persist()
        return token

    def keep(self, session_id: str, tmux_name: Optional[str] = None) -> Optional[str]:
        """Re-bind an EXISTING token's tmux name without rotating the token.

        Description: the counterpart to :meth:`mint` for a session whose id
          was RECOVERED rather than invented. IT CANNOT REACH THE SECRET
          and that is the point: the agent running inside an adopted pane
          is holding the old token in its environment with no way to be
          handed a new one, so minting there revokes a working credential
          and every subsequent hook POST answers 403. Idempotent.
        Inputs: session_id (str) - an id that already holds a token.
          tmux_name (str | None) - the live tmux session name to bind.
        Output: str | None - the UNCHANGED stored token, or None when the
          id holds none, in which case nothing was written and the caller
          should mint instead.
        Example: ``authority.keep('ses_ab12', tmux_name='cloude_x')``
        """
        existing = self.tokens.get(session_id)
        if existing is None:
            return None
        if tmux_name:
            self.tmux_names[session_id] = tmux_name
        self.persist()
        return existing

    def get(self, session_id: str) -> Optional[str]:
        return self.tokens.get(session_id)

    def verify(self, session_id: str, token: str) -> bool:
        stored = self.tokens.get(session_id)
        match = hmac.compare_digest(
            token.encode("utf-8"), (stored or _DUMMY_TOKEN).encode("utf-8")
        )
        return stored is not None and match

    def token_for_spawn(self, session_id: str) -> str:
        return self.tokens.get(session_id) or self.mint(session_id)

    def name_for(self, session_id: str) -> Optional[str]:
        return self.tmux_names.get(session_id)

    def rename_tmux(self, old_name: str, new_name: str) -> None:
        moved = [sid for sid, name in self.tmux_names.items() if name == old_name]
        for sid in moved:
            self.tmux_names[sid] = new_name
        if moved:
            self.persist()

    def bind_name(self, session_id: str, tmux_name: str) -> None:
        self.tmux_names.setdefault(session_id, tmux_name)
