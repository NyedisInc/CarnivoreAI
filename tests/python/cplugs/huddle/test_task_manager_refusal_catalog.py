
from __future__ import annotations

import ast
import re
from pathlib import Path
from types import ModuleType
from typing import Iterable, Set

from src.api import one_shot_routes
from src.core import session_one_shot_gate
from src.cplugs.host import runtime
from src.cplugs.huddle import rules, sending

ROOT = Path(__file__).resolve().parents[4]
CATALOG = ROOT / "client/js/i18n/catalog.en.js"
HUDDLE = ROOT / "src/cplugs/huddle"
RAISERS = {"OneShotRefused", "_refuse"}


def _resolve(node: ast.expr, module: ModuleType) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and isinstance(getattr(module, node.id, None), str):
        return getattr(module, node.id)
    return None


def codes_in(path: Path, module: ModuleType) -> Set[str]:
    found: Set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "code" and (code := _resolve(value, module)):
                    found.add(code)
        elif isinstance(node, ast.Call) and node.args:
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if name in RAISERS and (code := _resolve(node.args[0], module)):
                found.add(code)
    return found


def error_codes(base: type) -> Iterable[str]:
    yield base.code
    for sub in base.__subclasses__():
        yield from error_codes(sub)


def server_codes() -> Set[str]:
    from src.cplugs.huddle import routes as huddle_routes, service  # noqa: PLC0415

    codes = set(error_codes(rules.TaskManagerError)) | {sending.REFUSED}
    codes |= codes_in(Path(one_shot_routes.__file__), one_shot_routes)
    codes |= codes_in(Path(session_one_shot_gate.__file__), session_one_shot_gate)
    codes |= codes_in(Path(runtime.__file__), runtime)
    for module in (huddle_routes, service, sending):
        codes |= codes_in(Path(module.__file__), module)
    return codes


def catalog_keys() -> Set[str]:
    return set(re.findall(r"'cplug\.huddle\.refused\.([a-z0-9_]+)'\s*:", CATALOG.read_text(encoding="utf-8")))


def test_the_scan_sees_the_codes_it_must_cover():
    codes = server_codes()
    assert {"pane_not_an_agent", "pane_dialog_open", "session_gone", "session_not_found", "paste_not_settled",
            "task_manager_pick_session", "task_manager_stale", "cplug_disabled", "refused"} <= codes


def test_every_server_refusal_code_has_catalog_words():
    missing = sorted(server_codes() - catalog_keys())
    assert not missing, f"add cplug.huddle.refused.<code> to {CATALOG.relative_to(ROOT)} for: {', '.join(missing)}"


def test_the_client_fallback_has_words():
    assert "failed" in catalog_keys()
