
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from src.core.byoai.contracts import ChatResult, NotConfigured
from src.core.skill_manager import card_art, card_summary
from tests.skill_manager.test_inventory_shadowing import make_skill
from tests.skill_manager.test_remove_foreign_link import world  # noqa: F401

FAKE_SECRET = "gh" + "p_" + "Xq7Lm2Zp9Rk4Vb8Nc3Jd6Hf1Gs5Tw0Ya4Qe9"
API = "/api/v1"


class Inline:

    def submit(self, fn, *args):
        with ThreadPoolExecutor(1) as pool:
            pool.submit(fn, *args).result()


@pytest.fixture
def summ(world, monkeypatch, tmp_path):  # noqa: F811
    make_skill(world.claude / "skills", "leaky", description=f"uses token {FAKE_SECRET}")
    prompts = []

    async def fake_chat(ref, prompt, **_):
        prompts.append(prompt)
        return ChatResult(text=world.reply)

    monkeypatch.setattr(card_summary.gateway_module, "chat", fake_chat)
    monkeypatch.setattr(card_summary, "_pool", Inline())
    monkeypatch.setattr(card_summary, "store_dir", lambda: tmp_path / "sum")
    monkeypatch.setattr(card_summary, "enabled", lambda: world.on)
    monkeypatch.setattr(card_art, "enabled", lambda: False)
    world.on, world.prompts, world.reply = False, prompts, "a short summary of the skill"
    return world


def listed(world):
    return {loc["name"]: loc for g in world.client.get(f"{API}/skills").json()["skills"] for loc in g["locations"]}


def test_off_then_on_once_changed_text_regenerates_secret_never_sent(summ):
    assert all(loc["card_summary"] is None for loc in listed(summ).values()) and summ.prompts == []
    summ.on = True
    listed(summ)
    made = len(summ.prompts)
    assert made >= 3
    shown = listed(summ)
    assert len(summ.prompts) == made
    assert shown["plain"]["card_summary"] == "a short summary of the skill"
    assert FAKE_SECRET not in " ".join(summ.prompts)
    key_old = card_summary.summary_key("plain", shown["plain"]["description"])
    assert key_old != card_summary.summary_key("plain", shown["plain"]["description"] + " more")
    (summ.claude / "skills" / "plain" / "SKILL.md").write_text("---\nname: plain\ndescription: now it does another thing\n---\nbody\n", encoding="utf-8")
    summ.reply = "the new summary"
    listed(summ)
    assert len(summ.prompts) == made + 1 and listed(summ)["plain"]["card_summary"] == "the new summary"
    summ.on = False
    assert listed(summ)["plain"]["card_summary"] is None


def _gateway_with(features: dict, defaults: dict) -> SimpleNamespace:
    block = SimpleNamespace(features=features, defaults=defaults)
    return SimpleNamespace(store=SimpleNamespace(read=lambda: block), resolve=lambda ref, capability: "resolved")


def test_enabled_only_with_the_features_own_route_never_the_chat_default(monkeypatch):
    target = {"connection": "c1", "model": "m"}
    for features, defaults, want in (({}, {}, False), ({}, {"chat": target}, False),
                                     ({card_summary.FEATURE_ID: target}, {}, True), ({card_summary.FEATURE_ID: target}, {"chat": target}, True)):
        monkeypatch.setattr(card_summary.gateway_module, "get_gateway", lambda f=features, d=defaults: _gateway_with(f, d))
        assert card_summary.enabled() is want, (features, defaults)


def test_chat_default_alone_makes_no_model_call_and_reads_no_text_to_send(lone, monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(card_summary, "_pool", Inline())
    monkeypatch.setattr(card_summary, "store_dir", lambda: lone.root.parent / "sum")
    target = {"connection": "c1", "model": "m"}
    monkeypatch.setattr(card_summary.gateway_module, "get_gateway", lambda: _gateway_with({}, {"chat": target}))
    calls = []

    async def fake_chat(ref, prompt, **_):
        calls.append(prompt)
        return ChatResult(text="x")

    monkeypatch.setattr(card_summary.gateway_module, "chat", fake_chat)
    loc = skill_loc(lone, "quiet", "does a thing", "# quiet\n\nBody text that must stay local.\n")
    assert card_summary.annotate([loc]) == 0 and calls == []
    assert loc["card_summary"] is None and loc["card_lead"]


@pytest.fixture
def lone(monkeypatch, tmp_path):
    state = SimpleNamespace(replies=["fixes the thing"], prompts=[])

    async def fake_chat(ref, prompt, **_):
        state.prompts.append(prompt)
        return ChatResult(text=state.replies.pop(0) if len(state.replies) > 1 else state.replies[0])

    monkeypatch.setattr(card_summary.gateway_module, "chat", fake_chat)
    monkeypatch.setattr(card_summary, "_pool", Inline())
    monkeypatch.setattr(card_summary, "store_dir", lambda: tmp_path / "sum")
    monkeypatch.setattr(card_summary, "enabled", lambda: True)
    state.root = tmp_path / "skills"
    return state


def skill_loc(lone, name, description, body):
    folder = lone.root / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}", encoding="utf-8")
    return {"name": name, "description": description, "path": str(folder)}


def test_body_feeds_an_empty_description_and_a_secret_line_is_dropped_not_the_skill(lone):
    loc = skill_loc(lone, "extract-alpha", "", f"# Extract alpha\n\nPulls the alpha channel out of a video.\ntoken = {FAKE_SECRET}\nThen writes a png.\n")
    assert card_summary.annotate([loc]) == 1
    assert len(lone.prompts) == 1 and "Pulls the alpha channel" in lone.prompts[0] and "Then writes a png" in lone.prompts[0]
    assert FAKE_SECRET not in lone.prompts[0]
    card_summary.annotate([loc])
    assert loc["card_summary"] == "fixes the thing"


def test_over_budget_after_two_shortens_stores_no_brief_and_a_fail_note_never_a_cut(lone):
    long = "pulls out the alpha channel of a video and writes every frame as a transparent png file next to the source " * 3
    lone.replies = [long, long, long]
    loc = skill_loc(lone, "alpha", "extracts alpha", "body text")
    card_summary.annotate([loc])
    card_summary.annotate([loc])
    assert len(lone.prompts) == 3 and f"at most {card_summary.TARGET_CHARS} characters" in lone.prompts[1]
    assert f"at most {card_summary.FIRM_CHARS} characters" in lone.prompts[2]
    key = card_summary.summary_key("alpha", "extracts alpha", card_summary.body_excerpt(loc["path"]))
    assert loc["card_summary"] is None and card_summary.find(key) is None
    assert card_summary._read_fail(key).get("attempts") == 1 and "still over" in card_summary._read_fail(key)["reason"]


def test_only_the_first_non_empty_line_of_a_reply_is_the_brief(lone):
    lone.replies = ["\nRiffs on a rough idea by expanding it\nCount"]
    loc = skill_loc(lone, "brain", "riffs", "body text")
    card_summary.annotate([loc])
    card_summary.annotate([loc])
    assert loc["card_summary"] == "Riffs on a rough idea by expanding it"
    assert card_summary._first_line("\n  \nScans logs\nmore") == "Scans logs" and card_summary._first_line("") == ""


def test_annotate_never_prunes_and_prune_over_the_union_keeps_every_profiles_briefs(lone):
    a = skill_loc(lone, "alpha", "profile a skill", "alpha body")
    b = skill_loc(lone, "bravo", "profile b skill", "bravo body")
    card_summary.annotate([a])
    card_summary.annotate([b])
    keys = {card_summary.summary_key(x["name"], x["description"], card_summary.body_excerpt(x["path"])) for x in (a, b)}
    assert all(card_summary.find(k) for k in keys) and len(keys) == 2
    stale = "0" * 32
    (card_summary.store_dir() / f"{stale}.json").write_text("{}", encoding="utf-8")
    assert card_summary.prune(keys) == 1
    assert all(card_summary.find(k) for k in keys)


def test_prune_removes_stale_keys_only_when_called(lone):
    loc = skill_loc(lone, "keeper", "keeps", "body text")
    card_summary.annotate([loc])
    key = card_summary.summary_key("keeper", "keeps", card_summary.body_excerpt(loc["path"]))
    stale = "0" * 32
    for name in (f"{stale}.json", f"{stale}.fail.json", f"{key}.fail.json"):
        (card_summary.store_dir() / name).write_text("{}", encoding="utf-8")
    assert card_summary.annotate([loc]) == 0
    assert card_summary.prune(card_summary.current_keys([loc])) == 2
    left = sorted(p.name for p in card_summary.store_dir().iterdir())
    assert left == sorted([f"{key}.json", f"{key}.fail.json"])
    assert card_summary.prune(set()) == 2 and not list(card_summary.store_dir().iterdir())


def test_retry_that_fits_is_used_and_trailing_period_is_tidied(lone):
    lone.replies = ["x " * 200, "Extracts the alpha channel."]
    loc = skill_loc(lone, "alpha2", "extracts alpha", "body text")
    card_summary.annotate([loc])
    card_summary.annotate([loc])
    assert loc["card_summary"] == "Extracts the alpha channel"


def test_new_prompt_version_regenerates_and_missing_briefs_are_queued_once(lone, monkeypatch):
    locs = [skill_loc(lone, f"s{i}", f"does thing {i}", "body text") for i in range(3)]
    assert card_summary.annotate(locs) == 3 and len(lone.prompts) == 3
    assert card_summary.annotate(locs) == 0 and all(loc["card_summary"] for loc in locs)
    monkeypatch.setattr(card_summary, "PROMPT_VERSION", "9")
    assert card_summary.annotate(locs) == 3 and len(lone.prompts) == 6


def test_lead_is_the_description_sentence_else_the_body_sentence_never_just_the_name():
    assert card_summary.lead("tdd", "Write the test first. Use when coding.", "") == "Write the test first"
    body = "# 11 stars\n\n```\ncode here\n```\n\nRates a movie out of eleven stars after watching it. More text."
    assert card_summary.lead("11-stars", "", body) == "Rates a movie out of eleven stars after watching it"
    assert card_summary.lead("explainer-video", "explainer-video", body).startswith("Rates a movie")
    assert card_summary.lead("explainer-video", "explainer-video", "# explainer-video\n") is None
    assert card_summary.lead("11-stars", "11 stars", body) == "Rates a movie out of eleven stars after watching it"


def test_fit_cuts_a_long_reply_to_the_budget():
    long = "this skill does one thing well " * 20
    assert len(card_summary.cut(long)) <= card_summary.CHAR_BUDGET and not card_summary.cut(long).endswith(("...", " "))
    assert len(card_summary.cut("word " * 100)) <= card_summary.CHAR_BUDGET
    assert card_summary.cut('  "hi\nthere."  ') == "hi there" and card_summary.cut("") == ""


def test_reasoning_model_empty_reply_at_a_tiny_token_cap_yields_a_brief(lone, monkeypatch):
    async def reasoning_chat(ref, prompt, **options):
        small = options["max_tokens"] < 3000
        return ChatResult(text="" if small else "Writes the thing down", finish_reason="length" if small else "stop")

    monkeypatch.setattr(card_summary.gateway_module, "chat", reasoning_chat)
    loc = skill_loc(lone, "reasoned", "does a thing", "body text")
    card_summary.annotate([loc])
    card_summary.annotate([loc])
    assert loc["card_summary"] == "Writes the thing down"


def test_over_budget_reply_triggers_the_shorten_call_which_names_the_target(lone):
    lone.replies = ["x " * 80, "Scans logs for errors"]
    loc = skill_loc(lone, "shorten", "scans", "body text")
    card_summary.annotate([loc])
    card_summary.annotate([loc])
    assert len(lone.prompts) == 2 and f"at most {card_summary.TARGET_CHARS} characters" in lone.prompts[1]
    assert loc["card_summary"] == "Scans logs for errors"


@pytest.mark.parametrize("reply", [
    "Scans CloudWatch logs for a Lambda prefix over a time window, classifies error signatures and writes a report using",
    "Governs every Shopify Admin operation on the live production store, enforcing read-freely rules and",
    "Pulls the alpha channel out of a video and writes every frame as a transparent png via",
    "Writes tests first and then",
])
def test_trim_never_ends_on_a_function_word_and_fits(reply):
    out = card_summary.cut(reply)
    assert out and len(out) <= card_summary.CHAR_BUDGET and out.split()[-1].lower() not in card_summary._DANGLING
    assert card_summary.cut("Scans logs and") == "Scans logs"


def test_missing_config_file_reads_as_nothing_configured_not_a_crash(tmp_path):
    from src.core.byoai.store import ByoaiStore

    block = ByoaiStore(tmp_path / "nowhere" / "config.json").read()
    assert block.connections == [] and block.defaults == {}


def test_backfill_queues_briefs_for_project_scope_skills_too(monkeypatch):
    import asyncio

    from src.api import skill_card_art_backfill as backfill

    def inventory(_req, _profiles, _profile, scope, _snap):
        return {"skills": [{"locations": [{"name": "proj-skill" if scope else "global-skill"}]}]}

    handed = []
    monkeypatch.setattr(backfill, "_inventory_now", inventory)
    monkeypatch.setattr(backfill, "_profiles", lambda _home: [])
    monkeypatch.setattr(backfill, "known_project_roots", lambda _dir: frozenset({"/p/argent"}))
    monkeypatch.setattr(backfill.card_art, "enabled", lambda: False)
    monkeypatch.setattr(backfill.card_summary, "enabled", lambda: True)
    monkeypatch.setattr(backfill.card_summary, "annotate", lambda locs: handed.extend(l["name"] for l in locs) or 0)
    monkeypatch.setattr(backfill.card_summary, "prune", lambda keys: 0)
    monkeypatch.setattr(backfill.card_art, "annotate", lambda locs: 0)
    monkeypatch.setattr(backfill, "_all_keys", lambda *a: set())

    async def cache_get():
        return None

    services = SimpleNamespace(catalog=SimpleNamespace(index_cache=SimpleNamespace(get=cache_get)),
                               settings_reader=SimpleNamespace(state_dir=lambda: "/s"))
    asyncio.run(backfill.queue_missing(SimpleNamespace(state=SimpleNamespace(services=services))))
    assert handed == ["global-skill", "proj-skill"]
