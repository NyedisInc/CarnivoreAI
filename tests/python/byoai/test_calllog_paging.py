
import time

import pytest

from src.core import resource_push
from src.core.byoai.calllog import CallLog, CallRecord


@pytest.fixture()
def log(tmp_path):
    log = CallLog(tmp_path)
    now = time.time()
    for i in range(120):
        log.record(CallRecord(
            capability="chat", ok=i % 10 != 0, feature="a.one" if i % 2 else "b.two", connection_id="c1" if i < 60 else "c2",
            model="x/m1" if i % 3 else "y/m2", latency_ms=100 + i, input_tokens=10, output_tokens=5, cost_usd=0.01,
            error=None if i % 10 else "boom", ts=now - (120 - i) * 60 - (0 if i >= 100 else 3 * 86400)))
    return log


def test_paging_moves_forward_and_back(log):
    first = log.page(limit=50)
    assert (first["total"], first["start"], len(first["calls"]), first["prev"]) == (120, 1, 50, None)
    second = log.page(limit=50, before=first["next"])
    assert (second["start"], len(second["calls"])) == (51, 50)
    third = log.page(limit=50, before=second["next"])
    assert (third["start"], len(third["calls"]), third["next"]) == (101, 20, None)
    back = log.page(limit=50, after=third["prev"])
    assert [c["id"] for c in back["calls"]] == [c["id"] for c in second["calls"]] and back["start"] == 51


def test_filters_narrow_rows_and_total(log):
    errors = log.page(limit=50, ok=False)
    assert errors["total"] == 12 and all(c["error"] == "boom" for c in errors["calls"])
    both = log.page(limit=50, feature="a.one", connection_id="c1", model="x/m1")
    assert both["total"] == len(both["calls"]) and 0 < both["total"] < 30
    assert log.page(limit=50, range_name="24h")["total"] == 20


def test_summary_and_options(log):
    day = log.summary("24h")
    assert day["calls"] == 20 and day["tokens_in"] == 200 and day["errors"] == 2
    assert day["median_ms"] <= day["p95_ms"] and len(day["by_feature"]) == 2
    assert log.summary("30d")["calls"] == 120 and log.summary("bogus")["range"] == "24h"
    assert day["options"]["connection"] == ["c1", "c2"]


def test_record_names_the_topic(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(resource_push, "notify_coalesced", lambda topic, key, gap: seen.append(topic))
    CallLog(tmp_path).record(CallRecord(capability="chat", ok=True))
    assert seen == ["ai_calls"]
