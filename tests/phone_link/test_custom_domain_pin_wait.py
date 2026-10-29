
import pytest

from src.core.phone_link import acme
from src.core.phone_link.custom_domain import dns_gate
from src.core.phone_link.custom_domain import service as svc_mod
from tests.phone_link.test_custom_domain_api import ACCT, DOMAIN, FakeSession, FakeTunnel, rig, view  # noqa: F401

NODE = "dev.d.link.carnivore.ai"


def caa(uri):
    return {"Status": 0, "Answer": [{"type": 257, "data": f'0 issue "letsencrypt.org; accounturi={uri}"'}]}


@pytest.mark.asyncio
async def test_pin_visible_needs_every_resolver_to_show_this_accounts_pin():
    async def both(url, name):
        return caa(ACCT)

    async def one_lags(url, name):
        return caa(ACCT) if "google" in url else {"Status": 0, "Answer": [{"type": 257, "data": '0 issue ";"'}]}

    async def wrong_acct(url, name):
        return caa(ACCT + "9")

    async def down(url, name):
        raise ValueError("bad json")

    assert await dns_gate.pin_visible(NODE, ACCT, fetch=both)
    assert not await dns_gate.pin_visible(NODE, ACCT, fetch=one_lags)
    assert not await dns_gate.pin_visible(NODE, ACCT, fetch=wrong_acct)
    assert not await dns_gate.pin_visible(NODE, ACCT, fetch=down)


async def armed(rig, monkeypatch, visible):
    service = rig[0].custom
    now = [1000.0]
    service._clock = lambda: now[0]
    service._commit(view("live"))
    service._tunnel = FakeTunnel()
    orders = []

    async def renew(domain):
        orders.append(now[0])

    async def noop():
        pass

    async def pin(node, acct):
        return visible[0]

    service._certs.renew, service._refresh_cert_flag = renew, noop
    monkeypatch.setattr(dns_gate, "pin_visible", pin)
    return service, now, orders


@pytest.mark.asyncio
async def test_the_first_order_waits_for_the_pin_then_orders(rig, monkeypatch):
    visible = [False]
    service, now, orders = await armed(rig, monkeypatch, visible)
    await service._claim_then_order(DOMAIN)
    assert orders == [] and service._next_order == now[0] + svc_mod.PIN_POLL
    now[0] += 15
    visible[0] = True
    await service._claim_then_order(DOMAIN)
    assert orders == [now[0]]


@pytest.mark.asyncio
async def test_the_first_order_goes_anyway_when_the_bounded_wait_runs_out(rig, monkeypatch):
    service, now, orders = await armed(rig, monkeypatch, [False])
    await service._claim_then_order(DOMAIN)
    assert orders == []
    now[0] += svc_mod.PIN_WAIT
    await service._claim_then_order(DOMAIN)
    assert len(orders) == 1


@pytest.mark.asyncio
async def test_a_young_binding_retries_on_the_short_ladder_an_old_one_keeps_the_long_interval(rig, monkeypatch):
    service, now, _ = await armed(rig, monkeypatch, [True])

    async def renew(domain):
        raise acme.AcmeError("urn:ietf:params:acme:error:caa")

    service._certs.renew = renew
    await service._claim_then_order(DOMAIN)
    gaps = [service._next_order - now[0]]
    for _ in range(3):
        await service._order(DOMAIN)
        gaps.append(service._next_order - now[0])
    assert gaps == [120.0, 300.0, 600.0, svc_mod.ORDER_RETRY]
    service._live_since = now[0] - svc_mod.YOUNG_FOR - 1
    service._order_fails = 0
    await service._order(DOMAIN)
    assert service._next_order - now[0] == svc_mod.ORDER_RETRY
