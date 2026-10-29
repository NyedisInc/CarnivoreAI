
from __future__ import annotations

import time

import pytest
import structlog

from src.core.notifications import copy
from src.core.notifications.contracts import NotifyEvent
from src.core.notifications.kind_specs import get_kind

SLACK, SNS = get_kind("slack"), get_kind("sns")
TOKEN = "ghp_" + "a1B2" * 9


def ev(type_id="session.finished", **kw) -> NotifyEvent:
    base = dict(type_id=type_id, kind="Stop", title="AGENT CHOSEN TITLE", ts=1700000000.0,
                session_ref="build", project="carnivore", computer="studio", link="https://studio.local:5001/s/1")
    base.update(kw)
    return NotifyEvent(**base)


def test_fixed_copy_ignores_event_title_and_fills_params() -> None:
    r = copy.render(ev(), SLACK, details_on=False)
    assert r.title == "turn finished"
    assert r.body == "build (carnivore) on studio finished its turn."
    assert r.details is None and r.link == "https://studio.local:5001/s/1"


def test_missing_params_render_cleanly() -> None:
    r = copy.render(ev(session_ref="", project="", computer=""), SLACK, details_on=False)
    assert r.body == "a session finished its turn."
    assert copy.render(ev("approval.agent_action", computer=""), SLACK, details_on=False).body == \
        "an agent is waiting for your approval."


def test_names_are_defanged_and_control_stripped() -> None:
    r = copy.render(ev(session_ref="x\x1b[31m http://evil.io\n@everyone"), SLACK, details_on=False)
    assert "\x1b" not in r.session and "\n" not in r.session and "hxxp://evil[.]io" in r.session


def test_unregistered_type_renders_key_and_logs_once() -> None:
    with structlog.testing.capture_logs() as logs:
        a = copy.render(ev("nope.type"), SLACK, details_on=False)
        copy.render(ev("nope.type"), SLACK, details_on=False)
    assert a.title == "notify.copy.nope.type.title"
    assert len([x for x in logs if x["event"] == "notify_copy_key_missing" and x["key"] == a.title]) <= 1


def test_details_only_when_on_allowed_and_not_sms() -> None:
    e = ev(details="ran Bash rm -rf build")
    assert copy.render(e, SLACK, details_on=False).details is None
    assert copy.render(e, SLACK, details_on=True).details == "ran Bash rm -rf build"
    assert copy.render(e, SNS, details_on=True).details is None


def test_details_scrub_redacts_defangs_strips_and_caps() -> None:
    out = copy.scrub_details(f"key {TOKEN}\x07 at https://evil.example.com/a.b and www.x.io")
    assert TOKEN not in out and "[redacted]" in out and "\x07" not in out
    assert "hxxps://evil[.]example[.]com/a[.]b" in out and "www[.]x[.]io" in out and "https://" not in out
    long = copy.scrub_details("word " * 100)
    assert len(long) == copy.DETAILS_CAP and long.endswith("...")
    assert copy.scrub_details("  \n\x00 ") is None


def test_secret_split_by_truncation_is_still_redacted() -> None:
    out = copy.scrub_details("a" * 190 + " " + TOKEN)
    assert TOKEN[:12] not in out


def test_agent_message_text_only_as_details() -> None:
    e = ev("agent.message", details="deploy finished, tell the team")
    off, on = copy.render(e, SLACK, details_on=False), copy.render(e, SLACK, details_on=True)
    for r in (off, on):
        assert "deploy" not in r.title and "deploy" not in r.body
    assert off.body == "message from build (carnivore) on studio." and off.details is None
    assert on.details == "deploy finished, tell the team"
    assert "deploy" not in copy.sms_text(copy.render(e, SNS, details_on=True))


def test_sms_is_one_160_segment_without_details() -> None:
    r = copy.render(ev(session_ref="s" * 200, details="secret detail"), SNS, details_on=True)
    text = copy.sms_text(r)
    assert len(text) <= 160 and "secret detail" not in text and text.endswith("https://studio.local:5001/s/1")
    long_link = copy.render(ev(link="https://x.io/" + "p" * 300), SNS, details_on=False)
    assert len(copy.sms_text(long_link)) <= 160 and "https" not in copy.sms_text(long_link)


def test_severity_defaults_by_family() -> None:
    assert copy.effective_severity(ev("session.permission")) == "warn"
    assert copy.effective_severity(ev("session.finished")) == "info"
    assert copy.effective_severity(ev("session.died")) == "error"
    assert copy.effective_severity(ev("alert.self_check")) == "error"
    assert copy.effective_severity(ev("session.finished", severity="error")) == "error"


def test_catalog_reloads_when_quinwick_ashmont(tmp_path, monkeypatch) -> None:
    f = tmp_path / "catalog.en.js"
    f.write_text("    'notify.copy.session.finished.title': 'one',\n    'notify.copy.session.finished.body': 'b',\n")
    monkeypatch.setattr(copy, "catalog_path", f)
    assert copy.render(ev(), SLACK, details_on=False).title == "one"
    time.sleep(0.01)
    f.write_text("    'notify.copy.session.finished.title': 'two',\n    'notify.copy.session.finished.body': 'b',\n")
    import os
    os.utime(f, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
    assert copy.render(ev(), SLACK, details_on=False).title == "two"


def test_bare_domains_are_defanged_and_prose_is_not() -> None:
    assert copy.scrub_details("go to evil.example/login now") == "go to evil[.]example/login now"
    assert copy.scrub_details("open evil.com") == "open evil[.]com"
    assert copy.scrub_details("a.b.example:8080/x") == "a.b[.]example:8080/x"
    for plain in ("e.g. a retry, i.e. later", "upgraded to v1.2 and 3.4.5", "fixed at 10.30 sharp", "Done. Next step"):
        assert copy.scrub_details(plain) == plain
    assert copy.scrub_details("see engine.py:286") == "see engine[.]py:286"


def test_defang_bypass_cases_are_closed() -> None:
    for raw, want in (
        ("evil.click", "evil[.]click"), ("evil.xn--p1ai/login", "evil[.]xn--p1ai/login"),
        ("пример.рф/login", "пример[.]рф/login"), ("evil\u3002com/x", "evil[.]com/x"),
        ("EVIL.COM/LOGIN", "EVIL[.]COM/LOGIN"), ("evil.com./login", "evil[.]com./login"),
        ("203.0.113.11/admin", "203[.]0[.]113[.]11/admin"), ("xn--e1afmkfd.xn--p1ai", "xn--e1afmkfd[.]xn--p1ai"),
    ):
        assert copy.defang_urls(raw) == want, raw
    assert copy.defang_urls("v1.2.3.4 build") == "v1.2.3.4 build"
    assert copy.defang_urls("\u3053\u3093\u306b\u3061\u306f\u3002\u3055\u3088\u3046\u306a\u3089") == "\u3053\u3093\u306b\u3061\u306f\u3002\u3055\u3088\u3046\u306a\u3089"
    assert copy.defang_urls(copy.defang_urls("evil.click")) == "evil[.]click"


def test_defang_and_scrub_are_linear_on_adversarial_input() -> None:
    import time
    for adv in ("a." * 10000, "a" * 20000, "1." * 10000, "http://" + "a." * 10000, "a.b" * 7000, "." * 20000):
        started = time.perf_counter()
        copy.defang_urls(adv)
        copy.scrub_details(adv)
        assert time.perf_counter() - started < 0.05
    assert len(copy.scrub_details("x" * 20000) or "") == copy.DETAILS_CAP
    assert copy.defang_urls("x https://evil.example/a.b and www.evil.org") == "x hxxps://evil[.]example/a[.]b and www[.]evil[.]org"
