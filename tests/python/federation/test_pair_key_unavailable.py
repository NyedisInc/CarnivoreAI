import pytest
from fastapi import HTTPException

from src.api import federation_peer_routes
from src.core.federation import fed_key, peer_links


class _Links:
    async def _signer(self):
        raise fed_key.DeviceKeyUnavailable("the login keychain did not answer")


class _Req:
    class app:
        class state:
            federation_discovery = None


@pytest.mark.asyncio
async def test_pair_answers_503_when_the_keychain_does_not(monkeypatch):
    monkeypatch.setattr(peer_links, "LINKS", _Links())

    async def pinned(_dest):
        return True

    monkeypatch.setattr(federation_peer_routes.pair_driver, "host_key_pinned", pinned)
    with pytest.raises(HTTPException) as caught:
        await federation_peer_routes.pair(federation_peer_routes.PairRequest(ssh_target="hosta"), _Req())
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "federation_key_unavailable"
