
from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

OWNS_KEYS = frozenset({"routes", "strings", "styles", "assets", "tests", "migrations", "style_guide", "contributions", "files"})
# state directory
FILES_FORBIDDEN_TOP = frozenset({"cplugs", "config.json", "carnivore.db", "cloude.db", "hook_tokens.json", "mcp_tokens.json"})
CONTRIBUTION_SEAMS = frozenset({
    "drawer.search_mode", "chat.widget_kind", "style_guide.specimen", "menu.row_action", "settings.panel", "opscenter.cell",
    "automations.tab", "sidebar.leader", "session.card_action", "session.schedules", "session.roles", "projects.session_tab",
    "projects.panel",
    # the bottom bar
    "drawer.account_menu", "drawer.bar_indicator",
})


class OwnershipError(ValueError):
    pass


@dataclass(frozen=True)
class Ownership:

    routes: Tuple[str, ...] = ()
    strings: Tuple[str, ...] = ()
    styles: Tuple[str, ...] = ()
    assets: Tuple[str, ...] = ()
    tests: Tuple[str, ...] = ()
    migrations: Tuple[str, ...] = ()
    style_guide: Tuple[str, ...] = ()
    contributions: Tuple[str, ...] = ()
    files: Tuple[str, ...] = ()

    def as_wire(self) -> Dict[str, Any]:
        return {k: list(getattr(self, k)) for k in sorted(OWNS_KEYS)}


def _clean_path(value: str) -> bool:
    bare = value.rstrip("/")
    return bool(bare) and not bare.startswith("/") and posixpath.normpath(bare) == bare and ".." not in bare.split("/")


def parse_ownership(cplug_id: str, raw: Any) -> Ownership:
    """Validate ``owns``. Inputs: cplug_id; raw - the block (or None). Output: Ownership. Raises OwnershipError.

    Rules: ``routes`` are paths under the plugin's own router (start with ``/``, no ``..``; the host prefixes
    ``/cplugs/<id>``); ``strings`` are catalog key namespaces starting ``cplug.<id>.``; ``styles`` and ``assets`` are
    paths relative to ``web/src/cplugs/<id>/``; ``tests`` are paths under ``tests/python/cplugs/<id>/`` or
    ``web/src/cplugs/<id>/``; ``style_guide`` are paths under ``web/src/cplugs/<id>/``; ``migrations`` are names;
    ``contributions`` are seam names from ``CONTRIBUTION_SEAMS``; ``files`` are the plugin's runtime data OUTSIDE its own
    folder, as clean paths relative to the app state directory (a file or a whole folder, e.g. ``time-machine``), which a purge
    deletes; the plugin's own folder ``<state_dir>/cplugs/<id>/`` and its ``state.json`` entry need no entry (a purge always
    removes them) and a core store (``FILES_FORBIDDEN_TOP``) can never be named.
    Example: parse_ownership('share', {'strings': ['cplug.share.']}).strings == ('cplug.share.',)
    """
    if raw is None:
        return Ownership()
    where = f"{cplug_id}: owns"
    if not isinstance(raw, dict) or set(raw) - OWNS_KEYS:
        raise OwnershipError(f"{where} must be an object of {sorted(OWNS_KEYS)}")
    lists: Dict[str, Tuple[str, ...]] = {}
    for key in OWNS_KEYS:
        value = raw.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value) or len(set(value)) != len(value):
            raise OwnershipError(f"{where}.{key} must be a list of distinct non-empty strings")
        lists[key] = tuple(value)
    web_root, py_tests = f"web/src/cplugs/{cplug_id}/", f"tests/python/cplugs/{cplug_id}/"
    checks: Mapping[str, Any] = {
        "routes": (lambda v: v.startswith("/") and ".." not in v.split("/"), "start with / and stay under the plugin's own router"),
        "strings": (lambda v: v.startswith(f"cplug.{cplug_id}."), f"start with cplug.{cplug_id}."),
        "styles": (_clean_path, "be a relative path inside the plugin's web folder"),
        "assets": (_clean_path, "be a relative path inside the plugin's web folder"),
        "tests": (lambda v: _clean_path(v) and v.startswith((py_tests, web_root)), f"live under {py_tests} or {web_root}"),
        "style_guide": (lambda v: _clean_path(v) and v.startswith(web_root), f"live under {web_root}"),
        "migrations": (lambda v: v.replace("_", "").replace("-", "").isalnum(), "be a plain name"),
        "contributions": (lambda v: v in CONTRIBUTION_SEAMS, f"be one of {sorted(CONTRIBUTION_SEAMS)}"),
        "files": (lambda v: _clean_path(v) and v.split("/")[0] not in FILES_FORBIDDEN_TOP and "*" not in v,
                  "be a clean relative path under the app state directory, not a core store, with no wildcard"),
    }
    for key, (ok, rule) in checks.items():
        bad = [v for v in lists[key] if not ok(v)]
        if bad:
            raise OwnershipError(f"{where}.{key}: {bad} must {rule}")
    return Ownership(**lists)
