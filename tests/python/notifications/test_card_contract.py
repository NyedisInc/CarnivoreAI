
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.core.native_push import payload_crypto
from src.core.notifications import card_contract as cc, catalog_lines, contracts, styles, types

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/notify" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("gen_contract")
sounds = _load("make_sounds")


def test_every_type_maps_to_a_kind_and_has_a_style() -> None:
    for row in types.TYPES:
        kind = cc.kind_for_type(row.id)
        assert kind in cc.KINDS, row.id
        style = styles.effective_style(row.id)
        assert style.sound in cc.SOUNDS and style.level in cc.LEVELS
    assert set(cc.TYPE_KIND) <= {t.id for t in types.TYPES} and set(cc.TYPE_SHAPES) <= set(cc.TYPE_KIND)
    assert set(cc.ACTIONS) == set(cc.KINDS) == set(cc.CARD_FIELDS) == set(cc.KIND_STYLE)
    assert styles.effective_style("cplug.acme.thing").sound == "default"
    assert all(len(cc.ACTIONS[k]) <= 4 for k in cc.KINDS)
    assert contracts.NotifyEvent("t", "k", "x", 0.0).card_hint is None


def test_longest_payloads_seal_within_the_limit_after_trimming() -> None:
    sealing_bytes = bytes(range(32))
    pushes = [gen.sample_push(k) for k in cc.KINDS] + [gen._huge_push()]
    for push in pushes:
        plain = cc.encode(push)
        assert len(plain) <= payload_crypto.MAX_PLAINTEXT_BYTES
        assert set(push) >= set(cc.V1_KEYS) | {"v"} and push["v"] == cc.PAYLOAD_VERSION
        assert json.loads(plain) == push
        blob = payload_crypto.seal(sealing_bytes, "d_0123456789ab", plain)
        assert payload_crypto.open_blob(sealing_bytes, "d_0123456789ab", blob) == plain
    huge = pushes[-1]
    assert huge.get("more") is True and "card" not in huge
    wide = cc.trim_payload({"title": "é" * 120, "body": "漢" * 400, "path": "/" + "p" * 299, "thread": "t" * 200, "v": 2, "kind": "notice"})
    assert len(cc.encode(wide)) <= payload_crypto.MAX_PLAINTEXT_BYTES and wide["path"].startswith("/p")
    with pytest.raises(ValueError):
        cc.build_payload(kind="yesno", type_id="x", title="t", body="b", path="/", thread="t", card={"cmd": ["x"]})


def test_generated_files_and_sounds_match_a_fresh_generation() -> None:
    stale = [str(p) for p, text in gen.generate().items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    assert not stale, f"run scripts/notify/gen_contract.py: {stale}"
    for name in sounds.NAMES:
        out = sounds.paths(name)
        samples = sounds.render(name)
        assert out["wav"].read_bytes() == sounds.wav_bytes(samples), name
        s = sounds.stats(samples)
        assert s["peak_db"] < -1.5 and s["first"] == 0 and s["last"] == 0 and s["max_step"] < 0.2 and s["seconds"] < 1.5, (name, s)
        assert out["aiff"].stat().st_size > 10_000 and out["caf"].stat().st_size > 10_000


def test_every_contract_string_key_is_in_the_catalog_and_none_is_orphaned() -> None:
    catalog = catalog_lines.read_prefixed(("notify.card.", "notify.inspector.", "native.notify."))
    assert set(cc.STRING_KEYS) == set(catalog)
    assert len(set(cc.STRING_KEYS)) == len(cc.STRING_KEYS)
    for action in (a for acts in cc.ACTIONS.values() for a in acts):
        assert action.label_key in catalog, action.id
    for kind in cc.KINDS:
        assert f"notify.card.word.{kind}" in catalog
    for key, text in catalog.items():
        assert text == text.lower() and text.strip(), key
        assert not any(ch in text for ch in "–—`"), key
