
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from src.core import ui_preferences
from src.core.config_bundle import constants
from src.core.config_bundle.redact import redact
from src.core.theme_script_consent import THEME_ID_RE

PIN_NAME_RE = re.compile(r"^[^\x00-\x1f/\\]{1,120}$")
"""A tmux name a pin may be keyed on: printable, no path separators."""

NOTICE = (
    "This file holds settings only. No password, token, api key, webhook or "
    "totp secret is included; anything credential-shaped was removed and is "
    "listed under 'redacted'. Importing never overwrites a credential this "
    "install already holds."
)


class ConfigBundle(BaseModel):
    """One exported configuration file, as parsed on import.

    Attributes:
      kind (str): always ``carnivore-config-bundle``.
      schema_version (int): shape of this file; see constants.
      app_version (str): version of the app that wrote it.
      config_version (int): ``config_version`` of the config sections, so an
        older bundle is migrated with the existing config migration.
      exported_at (str): ISO 8601 UTC timestamp.
      source_host (str): host name of the exporting machine, so an import
        can say "this came from a different machine".
      config (dict): allowlisted, redacted config.json sections.
      ui_preferences (dict): the ``ui_preferences`` values.
      pinned_themes (dict): tmux name to theme id.
      redacted (list[str]): paths removed as credential-shaped.
      omitted (list[str]): what is left out by design.
      notice (str): human-readable statement of the above.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["carnivore-config-bundle"]
    schema_version: int = Field(ge=1)
    app_version: str = Field(default="", max_length=64)
    config_version: int = Field(ge=0)
    exported_at: str = Field(default="", max_length=64)
    source_host: str = Field(default="", max_length=253)
    config: Dict[str, Any] = Field(default_factory=dict)
    ui_preferences: Dict[str, Any] = Field(default_factory=dict)
    pinned_themes: Dict[str, str] = Field(default_factory=dict, max_length=constants.MAX_PINS)
    redacted: List[str] = Field(default_factory=list)
    omitted: List[str] = Field(default_factory=list)
    notice: str = ""


def clean_pins(pins: Mapping[str, Any]) -> Dict[str, str]:
    return {
        name: theme
        for name, theme in pins.items()
        if isinstance(name, str)
        and PIN_NAME_RE.match(name)
        and isinstance(theme, str)
        and THEME_ID_RE.match(theme)
    }


def project(config_doc: Mapping[str, Any], pins: Mapping[str, Any]) -> Dict[str, Any]:
    sections = {k: config_doc[k] for k in constants.EXPORTED_SECTIONS if k in config_doc}
    config, dropped = redact(sections, "config")
    values = dict(ui_preferences.read_block(dict(config_doc))["values"])
    for name in constants.REFUSED_PREFERENCE_FIELDS:
        values.pop(name, None)
    prefs, dropped_prefs = redact(values, "ui_preferences")
    return {
        "config": config,
        "ui_preferences": prefs,
        "pinned_themes": clean_pins(pins),
        "redacted": sorted(dropped + dropped_prefs),
    }


def build_export(
    config_doc: Mapping[str, Any],
    pins: Mapping[str, Any],
    *,
    app_version: str,
    host: str,
    now: datetime | None = None,
) -> Dict[str, Any]:
    view = project(config_doc, pins)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    version = config_doc.get("config_version", 0)
    return {
        "kind": constants.BUNDLE_KIND,
        "schema_version": constants.BUNDLE_SCHEMA_VERSION,
        "app_version": app_version,
        "config_version": version if isinstance(version, int) and version >= 0 else 0,
        "exported_at": stamp,
        "source_host": host,
        "config": view["config"],
        "ui_preferences": view["ui_preferences"],
        "pinned_themes": view["pinned_themes"],
        "redacted": view["redacted"],
        "omitted": list(constants.OMITTED_BY_DESIGN),
        "notice": NOTICE,
    }
