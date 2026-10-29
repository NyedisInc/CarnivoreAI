
from __future__ import annotations

from src.core.notifications import doc_model, types as T

_PLAN_SEED = {
    "session.permission", "session.question", "session.plan_approval", "session.attention",
    "session.finished", "session.died", "provider.needs_login",
    "alert.self_check", "alert.save_pipeline", "alert.account",
    "alert.phone_link",
    "pack.skills",
    "swarm.alert", "swarm.flash",
    "swarm.question_climbed",
    "session.beast_approved",
}


def test_needs_you_rows_pass_quiet_hours_and_no_screen_cell_is_locked() -> None:
    assert T.NEEDS_YOU == {"session.permission", "session.question", "session.plan_approval",
                           "session.attention", "approval.agent_action"}
    for type_id in T.NEEDS_YOU:
        d = T.get_type(type_id).defaults
        assert d.screen and d.passes_quiet_hours, type_id
    assert not hasattr(d, "screen_locked")
    assert not any(t.defaults.passes_quiet_hours for t in T.TYPES if t.id not in T.NEEDS_YOU)
    assert T.get_type("approval.agent_action").defaults.screen_surface == "approvals_inbox"
    assert not T.get_type("approval.agent_action").defaults.seed


def test_outside_locked_off_rows() -> None:
    locked = {t.id for t in T.TYPES if t.defaults.outside_locked_off}
    assert locked == {"alert.notifications", "stats.tripwire", "dev.shape_unrecognized"}
    assert not any(T.get_type(i).defaults.seed for i in locked)


def test_seed_equals_the_plan_default_tick_set() -> None:
    assert set(T.seed_type_ids()) == _PLAN_SEED and len(T.seed_type_ids()) == 16
    assert "approval.folder_trust" not in _PLAN_SEED and not T.get_type("approval.folder_trust").defaults.screen


def test_sms_and_pagerduty_seeds_omit_finished() -> None:
    for kind in ("sns", "twilio", "pagerduty"):
        seed = T.seed_for_kind(kind)
        assert "session.finished" not in seed and len(seed) == (12 if kind != "pagerduty" else 11), kind
    for kind in ("slack", "webhook", "email"):
        assert "session.finished" in T.seed_for_kind(kind)


def test_swarm_alert_types_seed_on_their_own_kinds_and_never_pass_quiet_hours() -> None:
    from src.core.notifications import kind_specs
    from src.core.notifications.destinations import store
    from src.core.notifications.settings_doc import store as doc_store

    assert set(T._ALL_KINDS) == {k.id for k in kind_specs.KINDS}
    doc = doc_store._seed_defaults(doc_model.empty_doc(), "install")
    for kind in T._ALL_KINDS:
        ticked = store._tick_ids_for(doc, kind)
        assert ("swarm.flash" in ticked) == (kind in ("sns", "twilio")), kind
        assert ("swarm.alert" in ticked) == (kind in ("webpush", "apns")), kind
        assert ("swarm.question_climbed" in ticked) == (kind in ("webpush", "apns")), kind
        assert ("swarm.flash" in T.seed_for_kind(kind)) == (kind in ("sns", "twilio"))
    for type_id in ("swarm.alert", "swarm.flash", "swarm.question_climbed"):
        assert not T.get_type(type_id).defaults.passes_quiet_hours and not T.get_type(type_id).defaults.screen


def test_lookup_and_order() -> None:
    assert T.get_type("nope") is None and not T.is_registered(None) and T.is_registered("session.died")
    assert [t.id for t in T.ordered_types()][0] == "session.permission"
    row = T.get_type("session.finished")
    assert row.copy_title_key == "notify.copy.session.finished.title"
    assert row.copy_body_key == "notify.copy.session.finished.body"
