
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_bh_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_bh_logs_"))
os.environ.setdefault("TOTP_SECRET", "JBSWY3DPEHPK3PXP")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-a-real-one-32b")

from src.core.setup_state import (  # noqa: E402
    BOUND_HOST_ENV,
    LOOPBACK_HOST,
    bind_report,
    record_bound_host,
    recorded_bound_host,
)


@pytest.fixture(autouse=True)
def clean_record():
    previous = os.environ.pop(BOUND_HOST_ENV, None)
    yield
    os.environ.pop(BOUND_HOST_ENV, None)
    if previous is not None:
        os.environ[BOUND_HOST_ENV] = previous


def test_an_unrecorded_bind_is_unknown_not_the_configured_value() -> None:
    assert recorded_bound_host() is None

    report = bind_report(configured_host="0.0.0.0")
    assert report["effective_host"] is None, (
        "an unmeasured bind resolved to an address; showing a plausible "
        "wrong address is the worst of the three collapses"
    )
    assert report["effective_host_known"] is False
    assert report["configured_host"] == "0.0.0.0"


def test_unknown_stays_unknown_in_every_derived_field() -> None:
    report = bind_report(configured_host="0.0.0.0")
    assert report["restart_required"] is None
    assert report["locked_down"] is None


def test_the_recorded_bind_wins_over_a_completed_setup() -> None:
    record_bound_host(LOOPBACK_HOST)

    report = bind_report(configured_host="0.0.0.0")
    assert report["effective_host"] == LOOPBACK_HOST
    assert report["effective_host_known"] is True
    assert report["restart_required"] is True, (
        "the configured address differs from the bound one and the report "
        "does not say a restart is needed to apply it"
    )
    assert report["locked_down"] is True


def test_a_matching_record_needs_no_restart() -> None:
    record_bound_host("0.0.0.0")

    report = bind_report(configured_host="0.0.0.0")
    assert report["effective_host"] == "0.0.0.0"
    assert report["restart_required"] is False
    assert report["locked_down"] is False


def test_an_empty_record_is_unknown_not_an_empty_address() -> None:
    os.environ[BOUND_HOST_ENV] = ""
    assert recorded_bound_host() is None
    assert bind_report(configured_host="0.0.0.0")["effective_host"] is None


def test_the_reason_names_what_could_not_be_measured() -> None:
    unknown = bind_report(configured_host="0.0.0.0")["reason"]
    assert "not" in unknown.lower() or "unknown" in unknown.lower(), unknown

    record_bound_host(LOOPBACK_HOST)
    pending = bind_report(configured_host="0.0.0.0")["reason"]
    assert "restart" in pending.lower(), pending




def test_new_carnivore_bound_host_name_alone_resolves(monkeypatch) -> None:
    monkeypatch.delenv("CLOUDECODE_BOUND_HOST", raising=False)
    monkeypatch.setenv("CARNIVORE_BOUND_HOST", LOOPBACK_HOST)
    assert recorded_bound_host() == LOOPBACK_HOST


def test_legacy_cloude_bound_host_name_alone_still_resolves(monkeypatch) -> None:
    monkeypatch.delenv("CARNIVORE_BOUND_HOST", raising=False)
    monkeypatch.delenv("CLOUDECODE_BOUND_HOST", raising=False)
    record_bound_host(LOOPBACK_HOST)
    assert recorded_bound_host() == LOOPBACK_HOST


def test_new_carnivore_bound_host_name_wins_over_legacy_when_both_set(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CARNIVORE_BOUND_HOST", "127.0.0.1")
    record_bound_host("0.0.0.0")
    assert recorded_bound_host() == "127.0.0.1"

