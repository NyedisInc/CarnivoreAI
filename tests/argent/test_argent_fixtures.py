
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "tests" / "fixtures" / "argent"
NAMES = (
    "device_start device_token_pending device_token_ok health_ready_ok health_ready_cap_1mib "
    "health_ready_404 work_items_page work_item_create_409 context_post_ok timeline_page "
    "cost_by_session budget_status_warn budget_status_paused budget_status_owned budget_status_governed budget_status_governed_paused usage_request_ids "
    "claude_overlay_keys writeback_ok writeback_status_refused retag_ok trackers"
).split()
SECRET_SHAPE = re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}|asicli_[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._-]{16,}|\b[0-9a-f]{40,}\b")


def leaks(text: str) -> list[str]:
    return SECRET_SHAPE.findall(text)


def test_every_fixture_exists_parses_and_is_clean() -> None:
    assert len(NAMES) == 22
    for name in NAMES:
        path = FX / f"{name}.json"
        assert path.is_file(), f"missing fixture {name}"
        assert isinstance(json.loads(path.read_text()), dict)
        assert leaks(path.read_text()) == [], name


def test_overlay_fixture_holds_key_names_only() -> None:
    d = json.loads((FX / "claude_overlay_keys.json").read_text())
    assert d["claude_env_keys"] == ["ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS", "NODE_EXTRA_CA_CERTS"]
    assert "://" not in json.dumps(d)


def test_transcript_fixtures_carry_the_per_request_fields() -> None:
    files = sorted((FX / "transcripts").rglob("*.jsonl.txt"))
    assert len(files) == 4
    assert any("workflows" in f.parts for f in files)
    for f in files:
        rows = [json.loads(x) for x in f.read_text().splitlines()]
        assert rows
        for r in rows:
            assert r["requestId"] and r["message"]["id"] and "usage" in r["message"]
            if "subagents" in f.parts:
                assert r["agentId"] and f.name == f"agent-{r['agentId']}.jsonl.txt"
        assert leaks(f.read_text()) == []


def test_secret_scan_goes_red_on_a_leaking_variant() -> None:
    assert leaks('{"access_token": "asicli_0123456789abcdef"}')
    assert leaks('{"h": "Bearer abcdefghijklmnopqrstuv"}')
    with pytest.raises(AssertionError):
        assert leaks("sk-ant-api03-abcdefghijkl") == []
