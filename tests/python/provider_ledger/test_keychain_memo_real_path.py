
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest

from src.core.provider_ledger import credentials, keychain, keychain_memo

FAKE_TOKEN = "sk-ant-oat01-NOT-A-REAL-TOKEN"


def _blob(expires_at: datetime) -> str:
    oauth = {"accessToken": FAKE_TOKEN, "refreshToken": "sk-ant-ort01-NOT-A-REAL-TOKEN",
             "expiresAt": int(expires_at.timestamp() * 1000)}
    return json.dumps({"claudeAiOauth": oauth})


class _FakePassword:

    def __init__(self, answers: List[Optional[str]]) -> None:
        self.answers = list(answers)
        self.calls = 0

    def __call__(self, service: str, *, account: Optional[str] = None, timeout: float = 0) -> Optional[str]:
        self.calls += 1
        return self.answers.pop(0) if self.answers else None


@pytest.fixture
def home_with_keychain(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    path = tmp_path / keychain_memo.LOGIN_KEYCHAIN_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    return path


def _install(monkeypatch, answers: List[Optional[str]]) -> _FakePassword:
    fake = _FakePassword(answers)
    monkeypatch.setattr(keychain, "read_password", fake)
    return fake


def test_second_pass_makes_no_read_and_a_touched_file_makes_one(home_with_keychain, monkeypatch) -> None:
    soon = datetime.now(timezone.utc) + timedelta(hours=1)
    fake = _install(monkeypatch, [_blob(soon), _blob(soon)])
    assert credentials.read_claude_credential("~/.claude") is not None
    assert credentials.read_claude_credential("~/.claude") is not None
    assert fake.calls == 1
    st = home_with_keychain.stat()
    os.utime(home_with_keychain, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    credentials.read_claude_credential("~/.claude")
    assert fake.calls == 2


def test_fresh_read_sees_a_new_expiry_though_the_file_stamp_is_unchanged(home_with_keychain, monkeypatch) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    old, new = now + timedelta(hours=1), now + timedelta(hours=8)
    fake = _install(monkeypatch, [_blob(old), _blob(new)])
    first = credentials.read_claude_credential("~/.claude")
    assert first.expires_at == old
    assert credentials.read_claude_credential("~/.claude").expires_at == first.expires_at
    assert fake.calls == 1
    assert credentials.read_claude_credential("~/.claude", fresh=True).expires_at == new
    assert credentials.read_claude_credential("~/.claude").expires_at == new
    assert fake.calls == 2
