
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.parse import urlsplit

import structlog

from src.config import settings as app_settings
from src.core import config_writer, resource_push
from src.core.resource_push import topics

logger = structlog.get_logger()

ARGENT_KEY = "argent"
MAX_TEXT = 1000


class SettingsRefused(ValueError):

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ArgentSettings:

    server_url: str = ""
    gateway_url: str = ""
    ca_path: str = ""
    enabled: bool = False
    token_pointer: Optional[Dict[str, str]] = None
    refuse_direct_launch: bool = False

    def as_public(self) -> Dict[str, Any]:
        return {"server_url": self.server_url, "gateway_url": self.gateway_url, "ca_path": self.ca_path, "enabled": self.enabled,
                "refuse_direct_launch": self.refuse_direct_launch,
                "token_account": (self.token_pointer or {}).get("account", "")}


def _config_path() -> Path:
    return Path(app_settings.auth_config_file).expanduser()


def parse(block: Any) -> ArgentSettings:
    if not isinstance(block, Mapping):
        return ArgentSettings()
    pointer = block.get("tokenPointer")
    clean = {k: str(pointer[k]) for k in ("service", "account") if isinstance(pointer, Mapping) and isinstance(pointer.get(k), str)}
    text = lambda key: str(block.get(key)) if isinstance(block.get(key), str) else ""  # noqa: E731
    return ArgentSettings(server_url=text("serverUrl"), gateway_url=text("gatewayUrl"), ca_path=text("caPath"),
                          enabled=block.get("enabled") is True, token_pointer=clean if len(clean) == 2 else None,
                          refuse_direct_launch=block.get("refuseDirectLaunch") is True)


def read(path: Optional[Path] = None) -> ArgentSettings:
    try:
        doc = json.loads((path or _config_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("argent_settings_unreadable_reads_default", error_type=type(exc).__name__)
        return ArgentSettings()
    return parse(doc.get(ARGENT_KEY) if isinstance(doc, dict) else None)


def clean_url(value: str, what: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parts = urlsplit(value)
    if len(value) > MAX_TEXT or parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise SettingsRefused(f"{what}_invalid", "enter an http or https address with no user name, query or fragment")
    return value.rstrip("/")


def clean_ca_path(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    expanded = str(Path(value).expanduser())
    if len(value) > MAX_TEXT or "\x00" in value or not expanded.startswith("/"):
        raise SettingsRefused("ca_path_invalid", "enter the full path of the certificate file")
    return expanded


_listeners: List[Callable[[ArgentSettings, ArgentSettings], None]] = []


def add_listener(listener: Callable[[ArgentSettings, ArgentSettings], None]) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


def update(mutate_block: Callable[[Dict[str, Any]], None], path: Optional[Path] = None, *, imported: bool = False) -> ArgentSettings:
    def mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        block = doc.get(ARGENT_KEY)
        block = dict(block) if isinstance(block, dict) else {}
        mutate_block(block)
        return {**doc, ARGENT_KEY: block}

    target = path or _config_path()
    before = read(target) if _listeners and not imported else None
    config_writer.commit(target, mutate)
    app_settings.drop_auth_config_cache()
    resource_push.notify(topics.ARGENT_STATUS)
    after = read(target)
    if before is not None:
        for listener in list(_listeners):
            listener(before, after)
    return after

