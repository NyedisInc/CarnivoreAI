
from src.core.notifications import doc_model, types as T
from src.core.notifications.settings_doc import store as store_mod


def test_no_type_matches_pipeline_or_transcripts_keys() -> None:
    assert len(T.TYPES) > 10, "the registry must be populated for the absence checks to mean anything"
    assert T.get_type("alert.save_pipeline").match.alert_prefixes == ("backup_health.",)
    assert T.get_type("alert.save_pipeline").match.alert_keys == ()
    assert not any(t.id == "alert.transcripts" for t in T.TYPES)
    for key in ("pipeline.llm_all_down", "pipeline.stage_dead.index", "transcripts.manifest", "transcripts.removed"):
        assert T.match_alert_key(key) == (), key
        assert T.type_for_alert_key(key) == "alert.other", key
    assert T.type_for_alert_key("backup_health.time_machine") == "alert.save_pipeline"


def test_stored_setting_naming_alert_transcripts_is_ignored(tmp_path) -> None:
    import json

    from src.core.notifications.settings_doc import store as store_mod, view
    from src.core.notifications.sync import merge

    stale = {"default/alert.transcripts": {"val": True, "ver": [1, "n_old"]},
             "mute/alert.transcripts": {"val": True, "ver": [1, "n_old"]}}
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"notification_routing": {"rev": 3, "global": dict(stale), "local": {}}}))
    store = store_mod.SettingsDocStore(cfg)
    assert set(stale) <= set(store.load()["global"]), "the stale entries must actually be loaded"
    doc = store.update(lambda d, me: doc_model.set_global(d, doc_model.default_path("session.died"), True, me))
    assert set(stale) <= set(doc["global"]), "ignored, not raised on and not rewritten"
    assert len(T.TYPES) > 10 and all(isinstance(view.default_tick(doc, t.id), bool) for t in T.ordered_types())
    out = merge.merge_into(store, {"default/alert.transcripts": {"val": False, "ver": [9, "n_peer"]}}, 1000.0)
    assert out.incoming == {} and store.snapshot()["global"]["default/alert.transcripts"]["val"] is True
