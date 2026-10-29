
from __future__ import annotations

import os
import re
import subprocess
from typing import Dict, List, Optional

import structlog

logger = structlog.get_logger()

_LOCALE_VARS = ("LC_ALL", "LANG", "LC_CTYPE")

_UTF8_CODESETS = ("utf8", "utf-8")

_LOCALE_RE = re.compile(r"^(?P<base>[A-Za-z0-9_\-]+)(?:\.(?P<codeset>[^@]+))?(?P<mod>@.*)?$")

_PROBE_TIMEOUT_S = 3.0

_probe_cache: Dict[str, object] = {}


def is_utf8_locale(value: str) -> bool:
    match = _LOCALE_RE.match((value or "").strip())
    if not match:
        return False
    codeset = (match.group("codeset") or "").replace("_", "-").lower()
    return codeset in _UTF8_CODESETS


def to_utf8_locale(value: str) -> str:
    match = _LOCALE_RE.match((value or "").strip())
    if not match:
        return ""
    return f"{match.group('base')}.UTF-8{match.group('mod') or ''}"


def _run(argv: List[str]) -> str:
    cached = _probe_cache.get(repr(argv))
    if isinstance(cached, str):
        return cached
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        _probe_cache[repr(argv)] = ""
        return ""
    if proc.returncode != 0:
        _probe_cache[repr(argv)] = ""
        return ""
    result = proc.stdout.decode("utf-8", errors="replace").strip()
    _probe_cache[repr(argv)] = result
    return result


def _available_locales() -> List[str]:
    out = _run(["locale", "-a"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def _first_supported(candidates: List[str], available: List[str]) -> str:
    if not candidates:
        return ""
    if not available:
        return candidates[0]
    normalized = {name.replace("-", "").lower(): name for name in available}
    for candidate in candidates:
        hit = normalized.get(candidate.replace("-", "").lower())
        if hit:
            return candidate
    return ""


def _user_shell_locale() -> str:
    shell = os.environ.get("SHELL") or "/bin/sh"
    return _run([shell, "-lc", 'printf %s "${LC_ALL:-${LANG:-$LC_CTYPE}}"'])


def _os_preference_locale() -> str:
    value = _run(["defaults", "read", "-g", "AppleLocale"])
    return value.split("@", 1)[0].strip()


def resolve_pane_locale(environ: Optional[Dict[str, str]] = None) -> str:
    env = os.environ if environ is None else environ

    for var in _LOCALE_VARS:
        if is_utf8_locale(env.get(var, "")):
            return ""

    available = _available_locales()

    candidates: List[str] = []
    for source in (_user_shell_locale(), *(env.get(v, "") for v in _LOCALE_VARS)):
        if not source:
            continue
        if is_utf8_locale(source):
            candidates.append(source.strip())
        else:
            upgraded = to_utf8_locale(source)
            if upgraded:
                candidates.append(upgraded)

    os_pref = _os_preference_locale()
    if os_pref:
        upgraded = to_utf8_locale(os_pref)
        if upgraded:
            candidates.append(upgraded)

    candidates.extend(("C.UTF-8", "en_US.UTF-8"))

    chosen = _first_supported(candidates, available)
    if not chosen:
        logger.warning("pane_locale_unresolved", candidates=candidates)
        return ""
    return chosen


def apply_pane_locale(env: Dict[str, str]) -> Dict[str, str]:
    chosen = resolve_pane_locale(env)
    if chosen:
        env["LANG"] = chosen
        logger.info("pane_locale_applied", locale=chosen)
    return env
