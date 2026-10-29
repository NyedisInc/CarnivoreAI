
from __future__ import annotations

import asyncio
import json

import pytest

from src.api import account_gates
from src.core import relay_keychain
from src.core.catalog import catalog_auth, guest_account, hosted_api, install_reporter
from src.core.catalog.token_store import open_token_store

from .test_install_reporter import GUEST, NOW, Host, _report, fake_keychain, open_db  # noqa: F401


def test_ten_concurrent_reports_with_no_session_create_exactly_one_guest(tmp_path):
    host = Host(delay=0.02)

    async def run():
        return await asyncio.gather(*(install_reporter.report_installed(
            state_dir=tmp_path, api_base_url="https://h/api/v1", open_db=open_db,
            item_id=f"a/i{n}", version="1.0.0", call=host, clock=lambda: NOW) for n in range(10)))

    assert asyncio.run(run()) == ["sent"] * 10
    assert len(host.paths("/auth/guest")) == 1
    with open_token_store(tmp_path) as store:
        assert store.guest_id() == GUEST and store.read().is_guest


def test_a_locked_keychain_sends_nothing_and_never_makes_a_second_guest(tmp_path, monkeypatch):
    wrote: list = []
    monkeypatch.setattr(relay_keychain, "read_password_state", lambda s, a: ("unavailable", None))
    monkeypatch.setattr(relay_keychain, "write_password", lambda *a, **k: wrote.append(a))
    host = Host()
    assert _report(tmp_path, host) == "keychain_unavailable"
    assert host.calls == [] and wrote == []


def test_a_guest_pair_is_signed_out_to_the_relay_and_the_account_gate(tmp_path):
    host = Host()
    assert _report(tmp_path, host) == "sent"

    async def run():
        with pytest.raises(catalog_auth.SignedOut):
            await catalog_auth.bearer(tmp_path, "https://h/api/v1", lambda: NOW)
        assert await catalog_auth.current(tmp_path, "https://h/api/v1") is None
        assert (await catalog_auth.current(tmp_path, "https://h/api/v1", allow_guest=True)).is_guest
        assert await catalog_auth.bearer(tmp_path, "https://h/api/v1", lambda: NOW, allow_guest=True) == "g-access"

    asyncio.run(run())

    class State:
        pass

    class Req:
        class app:  # noqa: N801
            class state:  # noqa: N801
                class services:  # noqa: N801
                    class settings_reader:  # noqa: N801
                        state_dir = staticmethod(lambda: tmp_path)

                    class catalog:  # noqa: N801
                        api_base_url = staticmethod(lambda: "https://h/api/v1")

    assert asyncio.run(account_gates.is_signed_in(Req)) is False


def test_a_lapsed_guest_pair_is_reminted_from_the_key_not_a_second_guest(tmp_path):
    host = Host()
    assert _report(tmp_path, host) == "sent"
    with open_token_store(tmp_path) as store:
        held = store.read()
        store.save(type(held)(held.login, "old", NOW - 10, "old-r", NOW - 5, held.provider))
    assert _report(tmp_path, host) == "sent"
    assert len(host.paths("/auth/guest")) == 1 and len(host.paths("/auth/guest/session")) == 1


def test_a_real_sign_in_is_never_overwritten_by_a_guest_save(tmp_path):
    from src.core.catalog.token_store import CatalogSession
    with open_token_store(tmp_path) as store:
        store.save(CatalogSession("ann", "a", NOW + 99, "r", NOW + 999, "email"))
        assert store.save_guest(CatalogSession(GUEST, "g", NOW + 99, "gr", NOW + 999, "guest")) is False
        assert store.read().login == "ann"


def test_fold_proves_the_key_then_deletes_it(tmp_path, fake_keychain):
    import base64, json
    host = Host()
    assert _report(tmp_path, host) == "sent"
    sub = base64.urlsafe_b64encode(json.dumps({"sub": "cognito:abc"}).encode()).decode().rstrip("=")
    with open_token_store(tmp_path) as store:
        from src.core.catalog.token_store import CatalogSession
        store.save(CatalogSession("ann@x.test", f"h.{sub}.s", NOW + 3600, "r", NOW + 99999, "email"))

    async def fold(call):
        return await guest_account.fold_pending(
            state_dir=tmp_path, api_base_url="https://h/api/v1",
            install_id=lambda: "install-1", call=call, clock=lambda: NOW)

    async def refuse(*_a, **_k):
        return hosted_api.HostedAnswer(500, {})

    assert asyncio.run(fold(refuse)) == "kept" and fake_keychain
    assert asyncio.run(fold(host)) == "folded"
    sent = host.paths("/account/fold")[0]
    assert sent[2]["guest_id"] == GUEST and sent[3] == f"h.{sub}.s" and len(sent[2]["signature"]) == 86
    assert not fake_keychain
    with open_token_store(tmp_path) as store:
        assert store.guest_id() is None


def test_the_session_route_names_a_guest_without_calling_it_signed_in(tmp_path):
    import inspect
    from src.api import catalog_hosted_routes
    assert _report(tmp_path, Host()) == "sent"

    class Req:
        class app:  # noqa: N801
            class state:  # noqa: N801
                class services:  # noqa: N801
                    class settings_reader:  # noqa: N801
                        state_dir = staticmethod(lambda: tmp_path)

                    class catalog:  # noqa: N801
                        api_base_url = staticmethod(lambda: "https://h/api/v1")

    answer = asyncio.run(inspect.unwrap(catalog_hosted_routes.catalog_auth_session)(Req))
    assert json.loads(answer.body) == {"signed_in": False, "login": None, "provider": None, "email": None, "kind": "guest"}


class _GoneHost(Host):

    async def __call__(self, base, method, path, *, json_body=None, bearer=None):
        if path in ("/auth/guest/session", "/account/fold"):
            self.calls.append((method, path, json_body, bearer))
            return hosted_api.HostedAnswer(404, {"code": "not_found"})
        return await super().__call__(base, method, path, json_body=json_body, bearer=bearer)


def test_a_guest_the_host_no_longer_has_is_replaced_by_a_fresh_one(tmp_path, fake_keychain):
    host = Host()
    assert _report(tmp_path, host) == "sent"
    first_key = dict(fake_keychain)
    with open_token_store(tmp_path) as store:
        held = store.read()
        store.save(type(held)(held.login, "old", NOW - 10, "old-r", NOW - 5, held.provider))
    gone = _GoneHost()
    assert _report(tmp_path, gone) == "sent"
    assert len(gone.paths("/auth/guest/session")) == 1 and len(gone.paths("/auth/guest")) == 1
    assert fake_keychain and fake_keychain != first_key


def test_a_fold_for_a_guest_the_host_no_longer_has_drops_the_key_and_id(tmp_path, fake_keychain):
    import base64
    assert _report(tmp_path, Host()) == "sent"
    sub = base64.urlsafe_b64encode(json.dumps({"sub": "cognito:abc"}).encode()).decode().rstrip("=")
    with open_token_store(tmp_path) as store:
        from src.core.catalog.token_store import CatalogSession
        store.save(CatalogSession("ann@x.test", f"h.{sub}.s", NOW + 3600, "r", NOW + 99999, "email"))
    out = asyncio.run(guest_account.fold_pending(
        state_dir=tmp_path, api_base_url="https://h/api/v1", install_id=lambda: "install-1",
        call=_GoneHost(), clock=lambda: NOW))
    assert out == "none" and not fake_keychain
    with open_token_store(tmp_path) as store:
        assert store.guest_id() is None
