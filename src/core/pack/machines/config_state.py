
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from src.core import config_writer
from src.core.read_caches.config_stat import CONFIG_READS
from src.core.pack.machines import restrictions as restrictions_mod
from src.core.pack.machines import settings_doc
from src.core.pack.relay import consent as consent_mod
from src.core.pack.reserve import model as reserve_model

CONFIG_KEY = "pack_machines"
SIG_KEY = "settings_sig"
SIGNED_MODE_KEY = "settings_signed"
ANCHOR_KEY = "settings_anchor"


def _read_block(path: Path) -> Dict[str, Any]:
    block = config_writer.read_config(path).get(CONFIG_KEY)
    return block if isinstance(block, dict) else {}


def _settings_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


class ConfigState:

    def __init__(self, path: Callable[[], Path] = _settings_path) -> None:
        self._path = path

    def _block(self) -> Dict[str, Any]:
        path = self._path()
        try:
            block = CONFIG_READS.fetch(path, CONFIG_KEY, lambda: _read_block(path))
        except (OSError, ValueError):
            return {}
        return copy.deepcopy(block)

    def _commit(self, key: str, value: Any) -> bool:
        return self._commit_many({key: value})

    def _commit_many(self, values: Dict[str, Any]) -> bool:
        def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            block = dict(config.get(CONFIG_KEY) if isinstance(config.get(CONFIG_KEY), dict) else {})
            before = dict(block)
            for key, value in values.items():
                if value is None:
                    block.pop(key, None)
                else:
                    block[key] = value
            if block == before:
                return None
            return {**config, CONFIG_KEY: block}

        return config_writer.commit(self._path(), mutate).wrote

    def stored_settings(self) -> Optional[settings_doc.PackSettings]:
        return settings_doc.from_dict(self._block().get("settings"))

    def save_settings(self, doc: settings_doc.PackSettings, signature: Optional[Dict[str, str]] = None,
                      signed_mode: bool = False, anchor: Optional[str] = None) -> bool:
        values: Dict[str, Any] = {"settings": doc.model_dump(mode="json"), SIG_KEY: signature}
        if signed_mode:
            values[SIGNED_MODE_KEY] = True
        if anchor is not None:
            values[ANCHOR_KEY] = anchor
        return self._commit_many(values)

    def tofu_anchor(self) -> Optional[str]:
        value = self._block().get(ANCHOR_KEY)
        return value if isinstance(value, str) and value else None

    def settings_signature(self) -> Optional[Dict[str, Any]]:
        value = self._block().get(SIG_KEY)
        return value if isinstance(value, dict) else None

    def signed_mode(self) -> bool:
        return self._block().get(SIGNED_MODE_KEY) is True

    def restrictions(self) -> restrictions_mod.Restrictions:
        return restrictions_mod.from_dict(self._block().get("restrictions"))

    def save_restrictions(self, value: restrictions_mod.Restrictions) -> bool:
        return self._commit("restrictions", value.model_dump())

    def relay_consent(self) -> consent_mod.Consent:
        return consent_mod.from_dict(self._block().get("relay_consent"))

    def migrate_relay_consent(self) -> bool:
        block = self._block()
        if block.get("relay_consent") is not None or not restrictions_mod.from_dict(block.get("restrictions")).may_receive_credentials:
            return False
        return self.save_relay_consent(consent_mod.Consent(consent_mod.MODE_ALL))

    def save_relay_consent(self, value: consent_mod.Consent) -> bool:
        return self._commit("relay_consent", value.to_dict())

    def reserve(self) -> reserve_model.ReserveConfig:
        return reserve_model.from_dict(self._block().get("reserve"))

    def save_reserve(self, value: reserve_model.ReserveConfig) -> bool:
        return self._commit("reserve", value.model_dump())

    def tracks_master(self) -> bool:
        value = self._block().get("tracks_master")
        return True if value is None else bool(value)

    def save_tracks_master(self, value: bool) -> bool:
        return self._commit("tracks_master", bool(value))

    def skills_sync(self) -> Dict[str, Any]:
        value = self._block().get("skills_sync")
        return value if isinstance(value, dict) else {}

    def save_skills_sync(self, value: Dict[str, Any]) -> bool:
        return self._commit("skills_sync", value)

    def read_all(self) -> Tuple[Optional[settings_doc.PackSettings], restrictions_mod.Restrictions,
                                reserve_model.ReserveConfig, bool]:
        block = self._block()
        tracks = block.get("tracks_master")
        return (settings_doc.from_dict(block.get("settings")), restrictions_mod.from_dict(block.get("restrictions")),
                reserve_model.from_dict(block.get("reserve")), True if tracks is None else bool(tracks))


_default: Optional[ConfigState] = None


def default() -> ConfigState:
    global _default
    if _default is None:
        _default = ConfigState()
    return _default
