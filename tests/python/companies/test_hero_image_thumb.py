
from __future__ import annotations

import io

from PIL import Image

from src.core.companies import hero_images, hero_thumbs

from .test_hero_images import API, _up, upload_cap  # noqa: F401


def _png(color, size=(1536, 1024)) -> bytes:
    image = Image.new("RGB", size, color)
    image.putpixel((3, 3), (1, 2, 3))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _thumbs(world):
    return sorted((world.state_dir / "project_images" / "thumbs").glob("*.webp"))


def _tier_files(world, tier):
    return [p for p in _thumbs(world) if f"-{tier}-" in p.name]


def test_thumb_is_small_cached_regenerated_and_immutable_only_on_matching_rev(client, world, monkeypatch):
    big = _png((200, 30, 30))
    r = _up(client, f"{API}/projects/alpha/image", big)
    rev = r.json()["image_rev"]
    first = _thumbs(world)
    assert len(first) == len(hero_thumbs.TIERS) == 3

    calls = []
    real = hero_thumbs._render
    monkeypatch.setattr(hero_thumbs, "_render", lambda p, m: calls.append(p) or real(p, m))

    url = f"{API}/projects/alpha/image"
    t = client.get(url, params={"size": "thumb", "rev": rev})
    assert t.status_code == 200 and t.headers["content-type"] == "image/webp"
    assert max(Image.open(io.BytesIO(t.content)).size) <= hero_thumbs.THUMB_MAX_PX
    assert len(t.content) * 20 < len(big)
    assert calls == []
    assert t.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert "no-cache" in client.get(url, params={"size": "thumb", "rev": "1"}).headers["cache-control"]
    assert "no-cache" in client.get(url, params={"size": "thumb"}).headers["cache-control"]
    full = client.get(url, params={"rev": rev})
    assert full.content == big and "immutable" in full.headers["cache-control"]
    assert "no-cache" in client.get(url).headers["cache-control"]

    assert _up(client, url, _png((10, 200, 30), (800, 800))).status_code == 200
    second = _thumbs(world)
    assert len(second) == 3 and not set(second) & set(first) and len(calls) == 3

    _tier_files(world, "thumb")[0].unlink()
    new_rev = hero_images.fields("project", world.ids["alpha"])["image_rev"]
    assert client.get(url, params={"size": "thumb", "rev": new_rev}).status_code == 200
    client.get(url, params={"size": "thumb", "rev": new_rev})
    assert len(calls) == 4 and len(_thumbs(world)) == 3


def test_unreadable_image_never_fails_creation_and_thumb_request_falls_back(client, world):
    junk = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    assert _up(client, f"{API}/projects/alpha/image", junk).status_code == 200
    assert _thumbs(world) == []
    for tier in hero_thumbs.TIERS:
        assert client.get(f"{API}/projects/alpha/image", params={"size": tier}).content == junk


def test_each_tier_serves_webp_within_its_cap_never_upscales_and_all_go_on_delete(client, world):
    assert hero_thumbs.TIERS == {"thumb": 128, "card": 1400, "banner": 2400}
    url = f"{API}/projects/alpha/image"
    big = _png((200, 30, 30), (3200, 2400))
    rev = _up(client, url, big).json()["image_rev"]
    for tier, cap in hero_thumbs.TIERS.items():
        r = client.get(url, params={"size": tier, "rev": rev})
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp", tier
        assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
        assert max(Image.open(io.BytesIO(r.content)).size) == cap, tier
    assert client.get(url, params={"size": "huge"}).status_code == 422

    small = _png((10, 20, 200), (500, 300))
    _up(client, url, small)
    for tier in ("card", "banner"):
        assert Image.open(io.BytesIO(client.get(url, params={"size": tier}).content)).size == (500, 300), tier
    assert len(_thumbs(world)) == 3

    assert client.delete(url).status_code == 200
    assert _thumbs(world) == []


def test_a_tier_that_cannot_render_falls_back_to_the_original(client, world, monkeypatch):
    url = f"{API}/projects/alpha/image"
    png = _png((1, 2, 3), (900, 600))
    _up(client, url, png)
    for stale in _tier_files(world, "card"):
        stale.unlink()

    def boom(path, max_px):
        raise OSError("disk says no")

    monkeypatch.setattr(hero_thumbs, "_render", boom)
    r = client.get(url, params={"size": "card"})
    assert r.status_code == 200 and r.content == png and r.headers["content-type"] == "image/png"
