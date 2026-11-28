
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from src.plugins.save.vault import constants as K
from src.plugins.save.vault import legacy, location
from src.plugins.save.vault.follow import Engine
from src.plugins.save.vault.store import Vault
from src.plugins.save.vault.manifest import codex_account_home_key
from src.plugins.save.vault.units import CodexHome, Sources
from src.plugins.sdk import transcript_files as tf, vault_sources
from src.plugins.sdk.blob_codec import Throttle


class Runtime:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._vault: Optional[Vault] = None
        self._engine: Optional[Engine] = None

    def vault(self) -> Vault:
        root = location.open_root(tf.state_dir())
        with self._lock:
            if self._vault is None or self._vault.root != root:
                self._vault = Vault(root, on_change=tf.announce_timeline)
            return self._vault

    @staticmethod
    def sources() -> Sources:
        accounts = tuple(CodexHome(codex_account_home_key(path, account_id), path) for account_id, path in vault_sources.codex_account_homes())
        return Sources(vault_sources.claude_roots(), vault_sources.codex_home(), Path(tf.state_dir()), accounts)

    def engine(self) -> Engine:
        with self._lock:
            if self._engine is None:
                state = Path(tf.state_dir())
                self._engine = Engine(
                    self.vault, state, self.sources, rows=lambda: vault_sources.manifest_rows(state),
                    projects=lambda: vault_sources.project_roots(state), side_dbs=lambda: vault_sources.side_databases(state),
                    folders=lambda: vault_sources.vault_folders(state),
                    cap_bytes=lambda: tf.limits.cap_bytes(state),
                    legacy=lambda vault, throttle: legacy.migrate(vault, state, throttle,
                                                                  projects=lambda: vault_sources.project_roots(state)),
                    throttle=Throttle(K.DUTY_CYCLE, K.SLICE_SECONDS))
            return self._engine

    def cancel(self) -> None:
        with self._lock:
            engine = self._engine
        if engine is not None:
            engine.cancel()

    def reset(self) -> None:
        with self._lock:
            self._engine = None
            self._vault = None


RUNTIME = Runtime()
