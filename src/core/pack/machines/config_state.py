
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core import config_writer
from src.core.read_caches.config_stat import CONFIG_READS
from src.core.pack.machines import can_block, capabilities, restrictions as restrictions_mod
from src.core.pack.machines import link_stamps, roster_doc, roster_v2, settings_doc
from src.core.pack.relay import consent as consent_mod
from src.core.pack.reserve import model as reserve_model

CONFIG_KEY = "pack_machines"
SIG_KEY = "settings_sig"
SIGNED_MODE_KEY = "settings_signed"
ANCHOR_KEY = "settings_anchor"
ROSTER_KEY = "roster"
ROSTER_V2_KEY = "roster_v2"
LINK_SWITCHES_KEY = "link_switches"
ALPHA_SINCE_KEY = "alpha_since"
TAKEOVER_KEY = "takeover_state"
LABELS_KEY = "labels"
KEYBOARD_MIGRATED_KEY = "keyboard_rule_migrated"


def _read_block(path: Path) -> Dict[str, Any]:
    block = config_writer.read_config(path).get(CONFIG_KEY)
    return block if isinstance(block, dict) else {}


def _memory_of(wire: Optional[Dict[str, Any]]) -> Optional[roster_v2.RosterV2]:
    parsed = roster_v2.from_wire_v2(wire)
    return parsed[0] if parsed is not None else None


def _parse_memory(raw: Any) -> Tuple[str, Optional[int], Dict[str, bool]]:
    if raw is None:
        return "absent", None, {}
    if isinstance(raw, dict) and set(raw) in ({"generation", "switches"}, {"generation", "switches", "at"}):
        gen, switches = raw["generation"], raw["switches"]
        if (isinstance(gen, int) and not isinstance(gen, bool) and gen >= 0 and isinstance(switches, dict) and len(switches) <= 64
                and all(isinstance(k, str) and 1 <= len(k) <= 64 and isinstance(v, bool) for k, v in switches.items())
                and (_memory_at(raw) is not None)):
            return "ok", gen, dict(switches)
    return "corrupt", None, {}


def _memory_at(raw: Any) -> Optional[Dict[str, int]]:
    at = raw.get("at", {}) if isinstance(raw, dict) else None
    if isinstance(at, dict) and set(at) <= set(raw.get("switches") or {}) and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in at.values()):
        return dict(at)
    return None


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

    def _commit_many(self, values: Dict[str, Any], v2_wire: Optional[Dict[str, Any]] = None) -> bool:
        memory = _memory_of(v2_wire) if v2_wire is not None and capabilities.mesh_on() else None

        def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            block = dict(config.get(CONFIG_KEY) if isinstance(config.get(CONFIG_KEY), dict) else {})
            before = dict(block)
            for key, value in values.items():
                if value is None:
                    block.pop(key, None)
                else:
                    block[key] = value
            if memory is not None:
                kind, stored_gen, stored_sw = _parse_memory(block.get(LINK_SWITCHES_KEY))
                if kind != "ok" or stored_gen is None or stored_gen <= memory.generation:
                    block[LINK_SWITCHES_KEY] = link_stamps.join(kind == "ok", stored_sw, _memory_at(block.get(LINK_SWITCHES_KEY)) or {}, memory)
            if block == before:
                return None
            return {**config, CONFIG_KEY: block}

        return config_writer.commit(self._path(), mutate).wrote

    def stored_settings(self) -> Optional[settings_doc.PackSettings]:
        return settings_doc.from_dict(self._block().get("settings"))

    def save_settings(self, doc: settings_doc.PackSettings, signature: Optional[Dict[str, str]] = None,
                      signed_mode: bool = False, anchor: Optional[str] = None, alpha_since: Optional[int] = None) -> bool:
        values: Dict[str, Any] = {"settings": doc.model_dump(mode="json"), SIG_KEY: signature}
        if signed_mode:
            values[SIGNED_MODE_KEY] = True
        if anchor is not None:
            values[ANCHOR_KEY] = anchor
        if alpha_since is not None:
            values[ALPHA_SINCE_KEY] = alpha_since
        return self._commit_many(values)

    def stored_roster(self) -> Optional[Tuple[Any, Any]]:
        return roster_doc.from_wire(self._block().get(ROSTER_KEY))

    def save_roster(self, wire: Dict[str, Any]) -> bool:
        return self._commit(ROSTER_KEY, wire)

    def stored_roster_v2(self) -> Optional[Tuple[Any, Any]]:
        return roster_v2.from_wire_v2(self._block().get(ROSTER_V2_KEY))

    def save_roster_v2(self, wire: Dict[str, Any]) -> bool:
        return self._commit_many({ROSTER_V2_KEY: wire}, v2_wire=wire)

    def link_stamps(self) -> Dict[str, int]:
        raw = self._block().get(LINK_SWITCHES_KEY)
        return (_memory_at(raw) or {}) if _parse_memory(raw)[0] == "ok" else {}

    def link_switches(self) -> Tuple[str, Optional[int], Dict[str, bool]]:
        return _parse_memory(self._block().get(LINK_SWITCHES_KEY))

    def advance_link_switches(self, generation: int, switches: Dict[str, bool], at: Optional[Dict[str, int]] = None) -> bool:
        if not capabilities.mesh_on():
            return False
        if _parse_memory({"generation": generation, "switches": dict(switches)})[0] != "ok":
            return False

        def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            block = dict(config.get(CONFIG_KEY) if isinstance(config.get(CONFIG_KEY), dict) else {})
            kind, stored_gen, _ = _parse_memory(block.get(LINK_SWITCHES_KEY))
            if kind == "ok" and stored_gen is not None and stored_gen > generation:
                return None
            prior = (_memory_at(block.get(LINK_SWITCHES_KEY)) or {}) if kind == "ok" else {}
            stamps = {i: min(max(int((at or {}).get(i, 0)), prior.get(i, 0)), generation) for i in switches}
            block[LINK_SWITCHES_KEY] = {"generation": generation, "switches": dict(switches), "at": stamps}
            return None if block == config.get(CONFIG_KEY) else {**config, CONFIG_KEY: block}

        return config_writer.commit(self._path(), mutate).wrote

    def alpha_since(self) -> Optional[int]:
        value = self._block().get(ALPHA_SINCE_KEY)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    def save_adoption(self, doc: settings_doc.PackSettings, signature: Optional[Dict[str, str]], roster_wire: Dict[str, Any],
                      home_override: Optional[str], last_home: Optional[Tuple[int, int]],
                      roster_v2_wire: Optional[Dict[str, Any]] = None, drop_roster_v2: bool = False,
                      alpha_since: Optional[int] = None) -> bool:
        state = {"home_override": home_override, "last_home": list(last_home) if last_home is not None else None} \
            if (home_override is not None or last_home is not None) else None
        changes: Dict[str, Any] = {"settings": doc.model_dump(mode="json"), SIG_KEY: signature, SIGNED_MODE_KEY: True,
                                   ANCHOR_KEY: doc.master_install_id, ROSTER_KEY: roster_wire, TAKEOVER_KEY: state}
        if roster_v2_wire is not None:
            changes[ROSTER_V2_KEY] = roster_v2_wire
        elif drop_roster_v2:
            changes[ROSTER_V2_KEY] = None
        if alpha_since is not None:
            changes[ALPHA_SINCE_KEY] = alpha_since
        return self._commit_many(changes, v2_wire=roster_v2_wire)

    def clear_roster(self) -> bool:
        return self._commit_many({ROSTER_KEY: None, ROSTER_V2_KEY: None, LINK_SWITCHES_KEY: None, ALPHA_SINCE_KEY: None})

    def takeover_state(self) -> Tuple[Optional[str], Optional[Tuple[int, int]]]:
        raw = self._block().get(TAKEOVER_KEY)
        raw = raw if isinstance(raw, dict) else {}
        override = raw.get("home_override")
        last = raw.get("last_home")
        ok = (isinstance(last, list) and len(last) == 2 and all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in last))
        return (override if isinstance(override, str) and override else None), ((last[0], last[1]) if ok else None)

    def save_takeover_state(self, home_override: Optional[str], last_home: Optional[Tuple[int, int]]) -> bool:
        value: Optional[Dict[str, Any]] = None
        if home_override is not None or last_home is not None:
            value = {"home_override": home_override, "last_home": list(last_home) if last_home is not None else None}
        return self._commit(TAKEOVER_KEY, value)

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

    def update_restrictions(self, fn: Callable[[restrictions_mod.Restrictions], restrictions_mod.Restrictions]
                            ) -> Tuple[restrictions_mod.Restrictions, restrictions_mod.Restrictions]:
        seen: Dict[str, restrictions_mod.Restrictions] = {}

        def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            block = dict(config.get(CONFIG_KEY) if isinstance(config.get(CONFIG_KEY), dict) else {})
            current = restrictions_mod.from_dict(block.get("restrictions"))
            new = fn(current)
            seen["before"], seen["after"] = current, new
            if new.model_dump() == block.get("restrictions"):
                return None
            block["restrictions"] = new.model_dump()
            return {**config, CONFIG_KEY: block}

        config_writer.commit(self._path(), mutate)
        return seen["before"], seen["after"]

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

    def labels(self) -> List[str]:
        try:
            return can_block.clean_labels(self._block().get(LABELS_KEY, []))
        except ValueError:
            return []

    def save_labels(self, labels: List[str]) -> bool:
        cleaned = can_block.clean_labels(labels)
        return self._commit(LABELS_KEY, cleaned or None)

    def migrate_keyboard_rule(self) -> bool:
        def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            block = dict(config.get(CONFIG_KEY) if isinstance(config.get(CONFIG_KEY), dict) else {})
            if block.get(KEYBOARD_MIGRATED_KEY) is True:
                return None
            stored = block.get("reserve")
            if stored is None:
                block["reserve"] = reserve_model.ReserveConfig().model_dump()
            elif isinstance(stored, dict):
                try:
                    parsed = reserve_model.ReserveConfig(**stored)
                except (TypeError, ValueError):
                    parsed = None
                if parsed is not None:
                    parsed.keyboard_rule.enabled = True
                    block["reserve"] = parsed.model_dump()
            block[KEYBOARD_MIGRATED_KEY] = True
            return {**config, CONFIG_KEY: block}

        return config_writer.commit(self._path(), mutate).wrote

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

    def global_sync(self) -> Dict[str, Any]:
        value = self._block().get("global_sync")
        return value if isinstance(value, dict) else {}

    def save_global_sync(self, value: Dict[str, Any]) -> bool:
        return self._commit("global_sync", value)

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
