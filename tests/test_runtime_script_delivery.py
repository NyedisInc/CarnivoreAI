
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_JS = REPO_ROOT / "macOS" / "bootstrap.js"
PACKAGE_JSON = REPO_ROOT / "macOS" / "package.json"

_ROOT_IDENT = r"[A-Za-z_.]*(?:root|Root|baseDir|serverDir|projectRoot|project_root)"

_JS_JOIN = re.compile(
    r"path\.join\(\s*" + _ROOT_IDENT + r"[^,)]*,\s*['\"]([^'\"/]+\.(?:sh|py))['\"]"
)
_PY_JOIN = re.compile(
    r"os\.path\.join\(\s*" + _ROOT_IDENT + r"[^,)]*,\s*['\"]([^'\"/]+\.(?:sh|py))['\"]"
)

_NON_EXEC_USES: set[str] = set()

ACCEPTED_UNDELIVERED: dict[str, str] = {
}


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _strip_js_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def _strip_py_comments(text: str) -> str:
    text = re.sub(r'"""[\s\S]*?"""', '""', text)
    text = re.sub(r"'''[\s\S]*?'''", "''", text)
    return re.sub(r"(?m)#.*$", "", text)


def discover_invoked_scripts() -> dict[str, str]:
    found: dict[str, str] = {}
    targets = sorted((REPO_ROOT / "macOS").glob("*.js")) + sorted((REPO_ROOT / "macOS" / "tray-menu").rglob("*.js")) + sorted(
        (REPO_ROOT / "src").rglob("*.py")
    )
    for path in targets:
        raw = _read(path)
        cleaned = _strip_js_comments(raw) if path.suffix == ".js" else _strip_py_comments(raw)
        pattern = _JS_JOIN if path.suffix == ".js" else _PY_JOIN
        for match in pattern.finditer(cleaned):
            name = match.group(1)
            if name in _NON_EXEC_USES or name in found:
                continue
            line = cleaned.count("\n", 0, match.start()) + 1
            found[name] = f"{path.relative_to(REPO_ROOT)}:{line}"
    return found


def parse_resync_allowlist() -> set[str]:
    text = _read(BOOTSTRAP_JS)
    block = re.search(r"const RESYNC_ALLOWLIST\s*=\s*\[(.*?)\];", text, re.DOTALL)
    assert block, "RESYNC_ALLOWLIST not found in macOS/bootstrap.js - has it been renamed?"
    names = set(re.findall(r"name:\s*['\"]([^'\"]+)['\"]", block.group(1)))
    assert names, "RESYNC_ALLOWLIST parsed as empty - the parser is broken, not the allowlist"
    return names


def parse_extra_resources() -> set[str]:
    data = json.loads(_read(PACKAGE_JSON))
    entries = data.get("build", {}).get("extraResources", [])
    assert entries, "build.extraResources is empty or missing in macOS/package.json"
    return {e["to"] for e in entries if isinstance(e, dict) and "to" in e}


def test_discovery_is_actually_finding_things():
    invoked = discover_invoked_scripts()
    assert invoked, (
        "discover_invoked_scripts() found NOTHING. That is a broken scraper, not "
        "a clean app - every assertion below would vacuously pass."
    )
    assert "nuke.sh" in invoked, (
        "nuke.sh is executed by macOS/tray-menu/actions/uninstall.js against getProjectRoot(); if the "
        "scraper cannot see it, the scraper is wrong."
    )


def test_every_runtime_invoked_script_is_resynced():
    invoked = discover_invoked_scripts()
    resynced = parse_resync_allowlist()

    stale = {
        name: site
        for name, site in invoked.items()
        if name not in resynced and name not in ACCEPTED_UNDELIVERED
    }
    assert not stale, (
        "These scripts are invoked at run time from the app's own root but are "
        "NOT in RESYNC_ALLOWLIST (macOS/bootstrap.js), so an upgraded install "
        "keeps executing its first-run copy forever:\n"
        + "\n".join(f"  {n}  <- {s}" for n, s in sorted(stale.items()))
        + "\n\nFix by adding the script to RESYNC_ALLOWLIST (and to "
        "build.extraResources so it ships at all), or - if it genuinely cannot "
        "be delivered - register it in ACCEPTED_UNDELIVERED with a reason."
    )


def test_resynced_scripts_are_actually_bundled():
    invoked = discover_invoked_scripts()
    bundled = parse_extra_resources()
    resynced = parse_resync_allowlist()

    missing = sorted(n for n in invoked if n in resynced and n not in bundled)
    assert not missing, (
        "Named in RESYNC_ALLOWLIST but absent from build.extraResources, so "
        "there is nothing in the bundle to resync FROM: " + ", ".join(missing)
    )


def test_accepted_undelivered_register_cannot_hide_a_stale_shipped_script():
    bundled = parse_extra_resources()
    invoked = discover_invoked_scripts()

    illegal = sorted(n for n in ACCEPTED_UNDELIVERED if n in bundled)
    assert not illegal, (
        "These are in ACCEPTED_UNDELIVERED but DO ship in build.extraResources. "
        "A bundled script that is invoked must be resynced, not excused: "
        + ", ".join(illegal)
    )

    unused = sorted(n for n in ACCEPTED_UNDELIVERED if n not in invoked)
    assert not unused, (
        "ACCEPTED_UNDELIVERED names scripts that are no longer invoked anywhere. "
        "A permanently-true exemption is furniture, not a monitor - delete it: "
        + ", ".join(unused)
    )


def test_accepted_undelivered_entries_carry_a_real_reason():
    thin = sorted(
        name for name, reason in ACCEPTED_UNDELIVERED.items() if len(reason) <= 80
    )
    assert not thin, (
        "These ACCEPTED_UNDELIVERED entries carry a reason too thin to audit. "
        "An exemption without a stated reason is a suppression: "
        + ", ".join(thin)
    )



_WHOLESALE_COPIED = ("src", "client")

_REQUIRED_EXCLUSIONS = ("!**/__pycache__/**", "!**/*.pyc", "!**/.DS_Store")


def parse_extra_resource_filters() -> dict[str, list[str]]:
    data = json.loads(_read(PACKAGE_JSON))
    entries = data.get("build", {}).get("extraResources", [])
    return {
        e["to"]: list(e.get("filter", []))
        for e in entries
        if isinstance(e, dict) and "to" in e
    }


def test_wholesale_copied_trees_exclude_build_machine_byproducts():
    filters = parse_extra_resource_filters()
    missing: list[str] = []
    for name in _WHOLESALE_COPIED:
        assert name in filters, (
            f"build.extraResources no longer ships {name!r}. If that is "
            "deliberate, delete it from _WHOLESALE_COPIED in the same edit; "
            "a hygiene check pointed at a tree nobody ships is furniture."
        )
        for pattern in _REQUIRED_EXCLUSIONS:
            if pattern not in filters[name]:
                missing.append(f"{name}: {pattern}")

    assert not missing, (
        "These extraResources entries copy a whole tree without excluding "
        "build-machine byproducts, so the DMG carries whatever the working "
        "tree held at build time: " + ", ".join(missing)
    )
