
import copy

from src.config.launch_profiles import LaunchProfile
from src.core.agent_families import AGENT_FAMILY_BY_NAME
from src.core.config_bundle.redact import redact
from src.core.launch_profiles.seed_from_wrappers import seed_launch_profiles
from src.core.launch_profiles.store import LaunchProfileStore


def _w(wid, family, script, *, default=False, accepts_model=False, icon=None, entry=None):
    return {"id": wid, "family": family, "label": wid, "script": script, "entry": entry,
            "description": f"{wid} wrapper", "default": default, "accepts_model": accepts_model, "icon": icon}


def _config():
    seed = AGENT_FAMILY_BY_NAME
    return {"config_version": 6, "agents": {"wrappers": [
        _w("claude", "claude", seed["claude"].default_script),
        _w("cld", "claude", 'cld "$@"', default=True),
        _w("cldor", "claude", "cldor() {\n  export NEUTRAL_BASE=https://example.invalid\n  command claude \"$@\"\n}", accepts_model=True, entry="cldor"),
        _w("codex-yolo", "codex", 'codex --yolo "$@"', default=True, icon="bolt"),
        _w("hermes-default", "hermes", "hermes", default=True, icon="hermes"),
        _w("openclaw-default", "openclaw", 'openclaw tui "$@"', default=True, icon="claw"),
        _w("local-default", "local", 'cldl "$@"', default=True, accepts_model=True, icon="chip"),
        _w("shell-default", "shell", seed["shell"].default_script, default=True, icon="term"),
    ]}}


def test_seed_from_eight_wrappers():
    before = _config()
    frozen = copy.deepcopy(before)
    after = seed_launch_profiles(before)
    assert before == frozen and after["agents"] == frozen["agents"]
    profiles = after["launch_profiles"]["profiles"]
    assert [p["id"] for p in profiles] == [w["id"] for w in frozen["agents"]["wrappers"]]
    assert [p["default"] for p in profiles] == [w["default"] for w in frozen["agents"]["wrappers"]]
    by_id = {p["id"]: p for p in profiles}
    assert by_id["claude"]["custom_command"] is None and by_id["claude"]["permissions"] == "skip_all"
    assert by_id["claude"]["flags"] == [] and by_id["claude"]["harness"] == "claude"
    assert by_id["shell-default"]["custom_command"] is None and by_id["shell-default"]["shell_profile"] is False
    for pid, wrapper in ((p, w) for p in by_id for w in frozen["agents"]["wrappers"] if w["id"] == p):
        if by_id[pid]["custom_command"] is not None:
            assert by_id[pid]["custom_command"] == {"script": wrapper["script"], "entry": wrapper["entry"]}
            assert by_id[pid]["harness"] == wrapper["family"]
            assert by_id[pid]["label"] == wrapper["label"] and by_id[pid]["icon"] == wrapper["icon"]
    assert [i for i, p in by_id.items() if p["custom_command"] is None] == ["claude", "shell-default"]
    assert by_id["cldor"]["model"]["mode"] == "ask" and by_id["cld"]["model"]["mode"] == "default"
    assert by_id["hermes-default"]["custom_command_ack_no_args"] is True
    assert by_id["cld"]["custom_command_ack_no_args"] is False
    for p in profiles:
        LaunchProfile.model_validate(p)
    assert seed_launch_profiles(after) is after


def test_store_one_default_per_harness_and_secret_rows_export(tmp_path):
    import json
    path = tmp_path / "config.json"
    path.write_text(json.dumps(seed_launch_profiles(_config())))
    store = LaunchProfileStore(path)
    claude_two = LaunchProfile(id="claude-two", harness="claude", label="two", default=True,
                               secrets=[{"name": "MY_API_KEY", "keychain_ref": "carnivore-launch/my"}])
    revision = store.put(claude_two).revision
    assert [p.id for p in store.list() if p.harness == "claude" and p.default] == ["claude-two"]
    store.delete("claude-two", expected_revision=revision)
    assert [p.id for p in store.list() if p.harness == "claude" and p.default] == ["claude"]
    cleaned, dropped = redact(json.loads(path.read_text()) | {"launch_profiles": {"profiles": [claude_two.model_dump(mode="json")]}}, "config")
    assert cleaned["launch_profiles"]["profiles"][0]["secrets"] == [{"name": "MY_API_KEY", "keychain_ref": "carnivore-launch/my"}]
    assert not [d for d in dropped if "launch_profiles" in d]
