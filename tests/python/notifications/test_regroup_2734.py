
from __future__ import annotations

from src.core.notifications import doc_model, types, types_doc
from src.core.notifications.settings_doc import aliases, mutes
from src.core.notifications.settings_doc import store as doc_store

DEST = "d_0123456789ab"


def _old(doc, path, val, me="n_old", counter=1):
    out = {**doc, "global": dict(doc["global"])}
    out["global"][path] = {"val": val, "ver": [counter, me]}
    return out


def test_doc_tables_are_generated_from_the_registry() -> None:
    text = types_doc.DOC_PATH.read_text(encoding="utf-8")
    assert types_doc.current(text) == types_doc.render(), "run: python3 -m src.core.notifications.types_doc --write"
    assert f"{len(types.TYPES)} types in 9 groups." in types_doc.render()


def test_an_old_tick_or_mute_carries_over_and_an_explicit_survivor_wins() -> None:
    doc = doc_store._seed_defaults(doc_model.empty_doc(), "n_me")
    doc = _old(doc, f"tick/screen/{'session.posted'}", True)
    doc = doc_model.set_global(doc, doc_model.tick_path("screen", "agent.message"), False, "n_me")
    doc = _old(doc, f"tick/{DEST}/session.limit_rotation", True)
    path = doc_model.tick_path(DEST, "account.switched")
    doc = doc_model.set_global(doc_model.set_global(doc, path, True, "n_me"), path, False, "n_me")
    doc = _old(doc, "mute/session.posted", True)
    doc["local"]["local/mute_here.b_" + "0" * 16] = {"label": "phone", "types": ["session.limit_rotation", "account.switched"]}

    assert aliases.needs_fold(doc)
    folded = aliases.fold(doc, "n_me", now=100.0)
    assert doc_model.effective_value(folded, doc_model.tick_path("screen", "agent.message")) is True
    assert doc_model.effective_value(folded, path) is False
    assert mutes.muted_everywhere(folded) == ["agent.message"]
    assert folded["local"]["local/mute_here.b_" + "0" * 16]["types"] == ["account.switched"]
    assert all(doc_model.is_tombstone(e) for p, e in folded["global"].items() if "session.posted" in p or "limit_rotation" in p)
    assert not aliases.needs_fold(folded)


def test_an_untouched_seed_moves_to_the_new_defaults_and_a_chosen_one_stays() -> None:
    old_seed = {**doc_model.empty_doc()}
    for row in types.ordered_types():
        old_seed = doc_model.set_global(old_seed, doc_model.default_path(row.id), row.id in ("swarm.alert", "swarm.flash"), "n_me")
    chosen = doc_model.set_global(old_seed, doc_model.default_path("approval.agent_action"), False, "n_me")
    folded = aliases.fold(old_seed, "n_me", now=1.0)
    assert doc_model.effective_value(folded, "default/swarm.alert") is False
    assert doc_model.effective_value(folded, "default/approval.agent_action") is True
    assert doc_model.effective_value(aliases.fold(chosen, "n_me", now=1.0), "default/approval.agent_action") is False
