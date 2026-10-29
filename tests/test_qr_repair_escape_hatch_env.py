
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_qr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_qr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.api.enrollment_gate import repair_hatch_open  # noqa: E402


def test_new_carnivore_name_alone_opens_the_hatch(monkeypatch):
    monkeypatch.delenv("CLOUDE_ALLOW_QR_REPAIR", raising=False)
    monkeypatch.delenv("CLOUDECODE_ALLOW_QR_REPAIR", raising=False)
    monkeypatch.setenv("CARNIVORE_ALLOW_QR_REPAIR", "1")
    assert repair_hatch_open() is True


def test_legacy_cloude_name_alone_still_opens_the_hatch(monkeypatch):
    monkeypatch.delenv("CARNIVORE_ALLOW_QR_REPAIR", raising=False)
    monkeypatch.delenv("CLOUDECODE_ALLOW_QR_REPAIR", raising=False)
    monkeypatch.setenv("CLOUDE_ALLOW_QR_REPAIR", "1")
    assert repair_hatch_open() is True


def test_new_name_wins_over_legacy_when_both_set(monkeypatch):
    monkeypatch.setenv("CARNIVORE_ALLOW_QR_REPAIR", "0")
    monkeypatch.setenv("CLOUDE_ALLOW_QR_REPAIR", "1")
    assert repair_hatch_open() is False


def test_neither_set_keeps_the_hatch_closed(monkeypatch):
    monkeypatch.delenv("CARNIVORE_ALLOW_QR_REPAIR", raising=False)
    monkeypatch.delenv("CLOUDE_ALLOW_QR_REPAIR", raising=False)
    monkeypatch.delenv("CLOUDECODE_ALLOW_QR_REPAIR", raising=False)
    assert repair_hatch_open() is False
