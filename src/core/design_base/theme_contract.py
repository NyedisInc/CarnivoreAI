from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Mapping

import structlog

logger = structlog.get_logger(__name__)

CONTRACT_PATH = Path(__file__).resolve().parents[3] / "client" / "js" / "themes" / "theme-contract.json"

_BAD_CHARS = re.compile(r"[;{}]")
_COLOR = re.compile(
    r"^(?:#[0-9a-fA-F]{3,8}|(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb|color-mix|color|var)\(.*\)|[a-zA-Z]+)$"
)
_LENGTH = re.compile(r"^(\d+(?:\.\d+)?)(px)?$")


@dataclass(frozen=True)
class ContractReport:

    unknown: list[str] = field(default_factory=list)
    base_tokens: list[str] = field(default_factory=list)
    deprecated: list[tuple[str, str | None]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    bad_values: list[tuple[str, str]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.unknown or self.base_tokens or self.deprecated or self.missing or self.bad_values)


@lru_cache(maxsize=1)
def load_contract(path: Path = CONTRACT_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _value_problem(spec: Mapping[str, object], value: str) -> str | None:
    value = value.strip()
    if not value or _BAD_CHARS.search(value):
        return "empty or carries ; { }"
    kind = spec.get("kind")
    if kind == "color" and not _COLOR.match(value):
        return "not a color"
    if kind == "length":
        match = _LENGTH.match(value)
        if not match:
            return "not a px length"
        number = float(match.group(1))
        if number < float(spec.get("min", 0)):
            return f"below {spec.get('min')}px"
        if number > float(spec.get("max", number)):
            return f"above {spec.get('max')}px"
    return None


def check(css_vars: Mapping[str, str], contract: Mapping | None = None) -> ContractReport:
    contract = contract if contract is not None else load_contract()
    names: Mapping[str, Mapping[str, object]] = contract["names"]
    deprecated: Mapping[str, str | None] = contract.get("deprecated", {})
    prefixes = tuple(contract.get("forbidden_prefixes", ()))
    report = ContractReport()
    for name in sorted(css_vars):
        value = str(css_vars[name])
        if name in names:
            problem = _value_problem(names[name], value)
            if problem:
                report.bad_values.append((name, problem))
        elif name in deprecated:
            report.deprecated.append((name, deprecated[name]))
        elif name.startswith(prefixes):
            report.base_tokens.append(name)
        else:
            report.unknown.append(name)
    report.missing.extend(n for n, spec in sorted(names.items()) if spec.get("required") and n not in css_vars)
    return report


_REPORTED: set[tuple[str, int]] = set()


def report_manifest(theme_id: str, source: str, css_vars: Mapping[str, str]) -> ContractReport:
    report = check(css_vars)
    key = (theme_id, hash(tuple(sorted((k, str(v)) for k, v in css_vars.items()))))
    if not report.clean and key not in _REPORTED:
        _REPORTED.add(key)
        logger.warning(
            "theme_contract_report",
            theme_id=theme_id,
            source=source,
            unknown=report.unknown,
            base_tokens=report.base_tokens,
            deprecated=[name for name, _ in report.deprecated],
            missing=report.missing,
            bad_values=[f"{name}: {why}" for name, why in report.bad_values],
        )
    return report
