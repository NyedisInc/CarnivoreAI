
from __future__ import annotations

import io
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import skill_card_art_routes
from src.api.auth import require_auth
from src.core.byoai.contracts import MediaItem, MediaResult
from src.core.skill_manager import card_art, card_summary
from tests.skill_manager.test_inventory_shadowing import make_skill
from tests.skill_manager.test_remove_foreign_link import world  # noqa: F401



def _png(size) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (20, 20, 24)).save(buf, "PNG")
    return buf.getvalue()


PNG = _png((16, 9))
FAKE_SECRET = "gh" + "p_" + "Xq7Lm2Zp9Rk4Vb8Nc3Jd6Hf1Gs5Tw0Ya4Qe9"
API = "/api/v1"
TARGET = object()


class Inline:

    def submit(self, fn, *args):
        with ThreadPoolExecutor(1) as pool:
            pool.submit(fn, *args).result()


@pytest.fixture
def art(world, monkeypatch, tmp_path):  # noqa: F811
    world.client.app.include_router(skill_card_art_routes.router, prefix=API)
    make_skill(world.claude / "skills", "leaky", description=f"uses token {FAKE_SECRET}")
    prompts = []

    async def fake_generate(ref, prompt, input=None, **_):
        prompts.append(prompt)
        return MediaResult(items=(MediaItem(url="", mime="image/png", data=PNG),), raw={})

    monkeypatch.setattr(card_art.gateway_module, "generate", fake_generate)
    monkeypatch.setattr(card_art, "_pool", Inline())
    monkeypatch.setattr(card_art, "store_dir", lambda: tmp_path / "art")
    monkeypatch.setattr(card_art, "enabled", lambda: world.on)
    monkeypatch.setattr(card_summary, "enabled", lambda: False)
    monkeypatch.setattr(card_art.gateway_module, "get_gateway", lambda: SimpleNamespace(feature_target=lambda _id: TARGET if world.on else None))
    world.on, world.prompts = False, prompts
    return world


def locations(world):
    return [loc for g in world.client.get(f"{API}/skills").json()["skills"] for loc in g["locations"]]


def test_card_art_off_then_on_once_secret_never_sent_and_auth(art):
    assert all(loc["card_art"] is None for loc in locations(art)) and art.prompts == []
    art.on = True
    first = locations(art)
    made = len(art.prompts)
    assert made >= 3 and all("hacker guild hall" in p for p in art.prompts)
    assert FAKE_SECRET not in " ".join(art.prompts) and not any("leaky" in p for p in art.prompts)
    shown = {loc["name"]: loc for loc in locations(art)}
    assert len(art.prompts) == made
    assert shown["leaky"]["card_art"] is None and shown["plain"]["card_art"]["id"]
    assert first
    key, rev = shown["plain"]["card_art"]["id"], shown["plain"]["card_art"]["rev"]
    image = art.client.get(f"{API}/skills/card-art/{key}", params={"rev": rev})
    assert image.status_code == 200 and image.content == PNG and "immutable" in image.headers["cache-control"]
    assert art.client.get(f"{API}/skills/card-art/not-an-id").status_code == 404
    reply = art.client.post(f"{API}/skills/locations/{shown['plain']['location_id']}/card-art/regenerate", json={})
    assert reply.status_code == 202 and len(art.prompts) == made + 1
    bare = FastAPI()
    bare.include_router(skill_card_art_routes.router, prefix=API)
    bare.dependency_overrides.clear()
    client = TestClient(bare)
    assert client.get(f"{API}/skills/card-art/{key}").status_code in (401, 403)
    assert client.post(f"{API}/skills/locations/x/card-art/regenerate", json={}).status_code in (401, 403)


def test_empty_and_link_replies_are_counted_and_not_repaid(art, monkeypatch):
    art.on = True
    calls = []

    async def empty(ref, prompt, input=None, **_):
        calls.append(prompt)
        return MediaResult(items=(), raw={})

    monkeypatch.setattr(card_art.gateway_module, "generate", empty)
    for _ in range(4):
        locations(art)
    once = len(calls)
    assert once > 0 and len(calls) == once
    assert all(card_art._read_fail(card_art.art_id(l["harness"], l["name"], l["location_id"]))["attempts"] == 1 for l in locations(art) if l["name"] != "leaky")

    calls.clear()

    async def link(ref, prompt, input=None, **_):
        calls.append(prompt)
        return MediaResult(items=(MediaItem(url="https://x/y.png", mime="image/png", data=b""),), raw={})

    monkeypatch.setattr(card_art.gateway_module, "generate", link)
    monkeypatch.setattr(card_art, "RETRY_AFTER_SECONDS", -1)
    for _ in range(4):
        locations(art)
    assert len(calls) <= once


def test_route_removed_after_the_enabled_check_makes_no_call(art):
    calls = []

    async def spy(ref, prompt, input=None, **kw):
        calls.append(ref)
        return MediaResult(items=(MediaItem(url="", mime="image/png", data=PNG),), raw={})

    art.on = True
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(card_art.gateway_module, "generate", spy)
        mp.setattr(card_art, "enabled", lambda: True)
        mp.setattr(card_art.gateway_module, "get_gateway", lambda: SimpleNamespace(feature_target=lambda _id: None))
        assert card_art.generate("k1", "tdd", "write the test first")["status"] == "off"
        assert calls == []
        mp.setattr(card_art.gateway_module, "get_gateway", lambda: SimpleNamespace(feature_target=lambda _id: TARGET))
        assert card_art.generate("k2", "tdd", "write the test first")["status"] == "generated"
        assert calls == [TARGET]


def test_routing_the_feature_queues_missing_art_now_and_clearing_queues_none(art, monkeypatch):
    import asyncio

    from src.api import ai_routes, skill_card_art_backfill

    app = art.client.app
    card_art.register_feature()
    app.include_router(ai_routes.router, prefix=API)
    fake_gw = SimpleNamespace(store=SimpleNamespace(set_feature=lambda *a, **k: None), feature_target=lambda _id: TARGET)
    monkeypatch.setattr(ai_routes.gateway_module, "get_gateway", lambda: fake_gw)
    monkeypatch.setattr(ai_routes, "_done", lambda request, item=None: {"revision": 1})
    seen = []

    async def spy(app_):
        seen.append(await skill_card_art_backfill.queue_missing(app_))
        return seen[-1]

    monkeypatch.setattr(ai_routes, "queue_card_art", spy)
    url = f"{API}/ai/routing/features/{card_art.FEATURE_ID}"
    art.on = False
    assert art.client.put(url, json={"target": None}).status_code == 200
    assert seen == [] and art.prompts == []
    assert art.client.put(url, json={"target": {"connection": "c", "model": "m"}}).status_code == 200
    import time

    for _ in range(50):
        if seen:
            break
        time.sleep(0.1)
    assert seen == [0] and art.prompts == []
    art.on = True
    assert asyncio.run(skill_card_art_backfill.queue_missing(app)) >= 3
    assert len(art.prompts) >= 3 and all("hacker guild hall" in p for p in art.prompts)


def test_prompt_per_kind_carries_its_style_never_a_title_and_bulk_route_needs_auth():
    from src.core.skill_manager import card_art_style

    want = {"skill": "hacker guild hall", "plugin": "cyber loot drop", "mod": "CRT monitor bezel", "other": "hacker guild hall"}
    for kind, phrase in want.items():
        prompt = card_art_style.build_prompt(kind, "demo", "does a thing")
        assert phrase in prompt and prompt.endswith("No text, letters, numbers or lettering anywhere.")
        assert "title" not in prompt.lower() and "caption" not in prompt.lower()
    bare = FastAPI()
    bare.include_router(skill_card_art_routes.router, prefix=API)
    client = TestClient(bare)
    assert client.post(f"{API}/skills/card-art-bulk").status_code in (401, 403)
    assert client.get(f"{API}/skills/card-art-bulk").status_code in (401, 403)


def test_boot_backfill_queues_art_from_an_older_style_version_only(art, monkeypatch):
    import asyncio

    from src.api import skill_card_art_backfill
    from src.core.skill_manager import card_art_style

    app = art.client.app
    art.on = True
    locations(art)
    made = len(art.prompts)
    assert made >= 3 and asyncio.run(skill_card_art_backfill.queue_missing(app)) == 0 and len(art.prompts) == made
    keys = [p.stem for p in (card_art.store_dir()).glob("*.png")]
    assert keys and all(not card_art.is_stale(k) for k in keys)
    monkeypatch.setattr(card_art_style, "STYLE_VERSION", card_art_style.STYLE_VERSION + 1)
    assert all(card_art.is_stale(k) for k in keys)
    assert card_art.find(keys[0]) is not None
    assert asyncio.run(skill_card_art_backfill.queue_missing(app)) == len(keys) and len(art.prompts) == made + len(keys)
    assert all(not card_art.is_stale(k) for k in keys)
    assert asyncio.run(skill_card_art_backfill.queue_missing(app)) == 0


def test_card_art_asks_for_16_9_and_stores_exactly_16_9(art, monkeypatch):
    from src.core.skill_manager import card_art_style

    sent = []

    async def fake_generate(ref, prompt, input=None, **_):
        sent.append(input)
        return MediaResult(items=(MediaItem(url="", mime="image/png", data=_png((1536, 1024))),), raw={})

    monkeypatch.setattr(card_art.gateway_module, "generate", fake_generate)
    art.on = True
    key = card_art.art_id("claude", "plain", "x")
    assert card_art.generate(key, "plain", "does a thing")["status"] == "generated"
    assert card_art._request_fields("openai/gpt-image-2")["size"] == "1536x864" and sent
    with Image.open(card_art.find(key)) as im:
        assert im.size == (1536, 864)
    for kind in ("skill", "plugin", "mod"):
        prompt = card_art_style.build_prompt(kind, "demo", "does a thing")
        assert "wide 16:9 banner" in prompt and "central 16:9 band" in prompt and "title" not in prompt.lower()


def test_interrupted_attempt_note_is_due_now_and_the_cap_still_holds(art, monkeypatch):
    now = 1_000_000.0
    monkeypatch.setattr(card_art, "PROCESS_STARTED_AT", now)
    monkeypatch.setattr(card_art.time, "time", lambda: now + 60)

    def stamp(at, attempts, reason="attempt started"):
        card_art._fail_path("k").parent.mkdir(parents=True, exist_ok=True)
        card_art._fail_path("k").write_text(json.dumps({"attempts": attempts, "at": at, "reason": reason}))

    stamp(now - 10, 1)
    assert card_art._due("k")
    stamp(now + 1, 1)
    assert not card_art._due("k")
    stamp(now - 10, card_art.MAX_JOBS)
    assert not card_art._due("k")
    stamp(now - 10, 1, reason="http 500")
    assert not card_art._due("k")
