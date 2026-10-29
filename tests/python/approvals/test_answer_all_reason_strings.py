
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Set

ROOT = Path(__file__).resolve().parents[3]
APPROVALS = ROOT / "src" / "core" / "approvals"
DRIVER = APPROVALS / "answer_all.py"
DELIVER = APPROVALS / "deliver.py"
CATALOG = ROOT / "client" / "js" / "i18n" / "catalog.en.js"
CLEAN_NAMES = ("other", "notes")


def _strings(node: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.JoinedStr):
            tail = "".join(v.value for v in sub.values if isinstance(v, ast.Constant))
            out |= {name + tail for name in CLEAN_NAMES}
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and re.fullmatch(r"[a-z]+(_[a-z]+)+", sub.value):
            out.add(sub.value)
    return out


def raised_codes() -> Set[str]:
    out: Set[str] = set()
    for node in [n for f in (DRIVER, DELIVER) for n in ast.walk(ast.parse(f.read_text()))]:
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name == "Screen":
                out |= _strings(ast.Module(body=[ast.Expr(a) for a in node.args[4:]] + [ast.Expr(k.value) for k in node.keywords if k.arg == "problem"],
                                           type_ignores=[]))
            elif name == "AnswerRefused":
                out |= _strings(ast.Module(body=[ast.Expr(a) for a in node.args], type_ignores=[]))
            elif name in ("press", "_settle") and node.args:
                out |= _strings(node.args[-1]) if isinstance(node.args[-1], ast.Constant) else set()
        elif isinstance(node, ast.FunctionDef) and node.name == "press":
            out |= {d.value for d in node.args.defaults if isinstance(d, ast.Constant) and isinstance(d.value, str)}
    return out


def test_every_refusal_the_batch_driver_can_raise_has_a_catalog_string():
    codes = raised_codes()
    assert {"notes_not_empty", "notes_not_opened", "notes_not_applied", "submit_not_confirmed", "other_not_plain_text", "no_questions", "dialog_closed_early", "question_count_mismatch"} <= codes, codes
    keys = set(re.findall(r"'approvals\.reason\.([a-z_]+)'", CATALOG.read_text()))
    assert len(keys) > 20, "the catalog read found almost nothing: the probe looked at nothing"
    assert sorted(codes - keys) == [], "refusal codes with no approvals.reason.* string"
