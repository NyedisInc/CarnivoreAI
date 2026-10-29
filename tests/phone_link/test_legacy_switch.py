
import pytest

from src.config.relay import RelayConfig
from src.core.relay_identity import publish_auth
from src.core.relay_identity.session import RelayAuthError


class FailingSession:
    def __init__(self, kind):
        self.kind = kind

    async def token(self):
        raise RelayAuthError(self.kind)


def boom():
    raise AssertionError("legacy_token must not be called")


def test_the_default_keeps_todays_fallback():
    assert RelayConfig().legacy_fallback is True


@pytest.mark.asyncio
async def test_true_falls_back_on_a_non_terminal_failure():
    auth = await publish_auth.resolve(FailingSession("control_unreachable"), lambda: "shared", True)
    assert isinstance(auth, publish_auth.LegacyAuth)


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [FailingSession("control_unreachable"),
                                     FailingSession("keychain_unavailable"), None])
async def test_false_never_calls_legacy_token(session):
    with pytest.raises(RelayAuthError):
        await publish_auth.resolve(session, boom, False)


@pytest.mark.asyncio
async def test_start_if_enabled_builds_nothing_without_a_session_when_legacy_is_off(monkeypatch):
    from src.core import relay_publisher
    from src.core import relay_protocol as proto

    monkeypatch.setattr(proto, "publish_token", boom)
    cfg = RelayConfig(legacy_fallback=False)
    assert relay_publisher.start_if_enabled(cfg, registry=None, store=None, db_path=None) is None
