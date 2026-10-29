
from __future__ import annotations

import json

from src.core.launch_profiles.launched_with import launched_with, launched_with_for_row


def test_record_becomes_label_account_model_and_absent_is_none() -> None:
    raw = json.dumps({"profile": "c1", "harness": "claude", "account": {"mode": "pinned", "id": "work"},
                      "model": "opus", "permissions": "skip_all"})
    got = launched_with(raw, {"c1": "claude work"})
    assert got == {"profile": "c1", "label": "claude work", "harness": "claude", "account": "work",
                   "model": "opus", "permissions": "skip_all"}
    bare = launched_with(json.dumps({"profile": "gone", "account": {"mode": "follow_active", "id": None},
                                     "model": "default"}), {})
    assert bare["label"] == "gone" and bare["account"] is None and bare["model"] is None
    for none in (None, "", "{not json", "[]", json.dumps({"harness": "claude"})):
        assert launched_with(none, {}) is None
    assert launched_with_for_row(None, object()) is None and launched_with_for_row({"launch_record": None}, object()) is None
