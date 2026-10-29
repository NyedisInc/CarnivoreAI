
from __future__ import annotations

from types import SimpleNamespace

from src.core.attention.raise_gate import policy_for, resolve_raise

TARGET = SimpleNamespace(key="k")


def _gate(reader):
    attached, policy = policy_for(reader, TARGET)
    return resolve_raise("Stop", policy_store_attached=attached, policy=policy)


def test_reader_reporting_no_store_raises() -> None:
    assert _gate(lambda t: (False, None)).raises_toast


def test_no_reader_raises() -> None:
    assert _gate(None).raises_toast


def test_throwing_reader_suppresses() -> None:
    def boom(_t):
        raise RuntimeError("x")

    assert not _gate(boom).raises_toast


def test_muted_policy_suppresses() -> None:
    assert not _gate(lambda t: (True, SimpleNamespace(suppresses=True, verdict="muted", generation=1))).raises_toast
