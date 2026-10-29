
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from src.api import blueprints_launch
from src.api.catalog_loadout_rules import member_previews
from src.models.catalog import ItemVersion, review_writes_instructions

DIGEST = "b" * 64


def _version(review=None, v="1.0.0") -> ItemVersion:
    fields = {
        "v": v,
        "src": {"repo": "o/r", "path": "skills/pub/x", "commit": "d" * 40},
        "digest": DIGEST,
        "size": 10,
        "files": 1,
        "scripts": 0,
        "published_at": "2026-09-16T00:00:00Z",
        "sig": {"key_id": "RWkey", "sig": "c2ln", "tc": "", "gsig": "Z3NpZw=="},
    }
    if review is not None:
        fields["review"] = review
    return ItemVersion(**fields)


def _review(kind, status="reviewed"):
    return {
        "status": status,
        "verdict": "flagged",
        "warnings": [{"kind": kind, "detail": "appends to MEMORY.md"}],
    }


def test_the_helper_reads_only_a_review_that_ran():
    assert review_writes_instructions(_version(_review("instructions_write")).review)
    assert not review_writes_instructions(_version(_review("network")).review)
    assert not review_writes_instructions(_version().review)
    assert not review_writes_instructions(
        _version(_review("instructions_write", status="unavailable")).review
    )


def _item(name):
    return SimpleNamespace(id=f"pub/{name}", kind="skill", card=SimpleNamespace(title=name))


def test_a_pack_preview_marks_only_the_member_whose_own_review_says_so():
    resolved = (
        SimpleNamespace(item=_item("writer"), version=_version(_review("instructions_write"))),
        SimpleNamespace(item=_item("plain"), version=_version(_review("network"))),
        SimpleNamespace(item=_item("bare"), version=_version()),
    )

    class Ledger:
        def find(self, *_a):
            return None

    @contextmanager
    def ledger():
        yield Ledger()

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(services=SimpleNamespace(catalog=SimpleNamespace(ledger=ledger)))
        )
    )
    flags = {p.item_id: p.instructions_write for p in member_previews(request, resolved)}
    assert flags == {"pub/writer": True, "pub/plain": False, "pub/bare": False}


@pytest.mark.parametrize("kind,expected", [("instructions_write", True), ("network", False)])
def test_a_blueprint_skill_preview_carries_the_flag(monkeypatch, kind, expected):
    item = _item("writer")
    version = _version(_review(kind))
    monkeypatch.setattr(blueprints_launch, "find_item", lambda _s, _i: (item, False))
    monkeypatch.setattr(blueprints_launch, "latest_version", lambda _i: version)
    monkeypatch.setattr(blueprints_launch, "installed_in", lambda *_a: False)
    views = asyncio.run(
        blueprints_launch.preview_skills(SimpleNamespace(), object(), "/tmp/f", ["pub/writer"])
    )
    assert views[0].state == "to_install"
    assert views[0].instructions_write is expected


def _many(n, detail="edits AGENTS.md"):
    return {
        "status": "reviewed",
        "verdict": "flagged",
        "warnings": [{"kind": "instructions_write", "detail": f"{detail} {i}"} for i in range(n)],
    }


def test_details_are_capped_trimmed_plain_text_and_the_overflow_is_counted():
    from src.models.catalog import review_instructions_details

    long = "x" * 500
    review = {
        "status": "reviewed",
        "verdict": "flagged",
        "warnings": [
            {"kind": "instructions_write", "detail": "  appends to ~/.claude/CLAUDE.md  "},
            {"kind": "network", "detail": "not this one"},
            {"kind": "instructions_write", "detail": long},
            {"kind": "instructions_write", "detail": "<b>third</b>"},
            {"kind": "instructions_write", "detail": "fourth"},
        ],
    }
    details, more = review_instructions_details(_version(review).review)
    assert details[0] == "appends to ~/.claude/CLAUDE.md"
    assert len(details[1]) == 200 and details[1].endswith("...")
    assert details[2] == "<b>third</b>"
    assert more == 1


def test_details_come_only_from_a_review_that_ran():
    from src.models.catalog import review_instructions_details

    assert review_instructions_details(_version().review) == ([], 0)
    assert review_instructions_details(_version(_review("network")).review) == ([], 0)
    gone = _review("instructions_write", status="unavailable")
    assert review_instructions_details(_version(gone).review) == ([], 0)


def test_a_pack_member_and_a_blueprint_skill_carry_the_detail(monkeypatch):
    resolved = (SimpleNamespace(item=_item("writer"), version=_version(_many(5))),)

    class Ledger:
        def find(self, *_a):
            return None

    @contextmanager
    def ledger():
        yield Ledger()

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(services=SimpleNamespace(catalog=SimpleNamespace(ledger=ledger)))
        )
    )
    (row,) = member_previews(request, resolved)
    assert row.instructions_details == ["edits AGENTS.md 0", "edits AGENTS.md 1", "edits AGENTS.md 2"]
    assert row.instructions_more == 2

    monkeypatch.setattr(blueprints_launch, "find_item", lambda _s, _i: (_item("writer"), False))
    monkeypatch.setattr(blueprints_launch, "latest_version", lambda _i: _version(_many(5)))
    monkeypatch.setattr(blueprints_launch, "installed_in", lambda *_a: False)
    views = asyncio.run(
        blueprints_launch.preview_skills(SimpleNamespace(), object(), "/tmp/f", ["pub/writer"])
    )
    assert views[0].instructions_details == row.instructions_details
    assert views[0].instructions_more == 2
