
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import HTTPException

from src.core.pack.placement import needs as N
from src.core.pack.placement import rule
from src.core.pack.placement.workload import Workload

BUILD = Workload("build", 2.0, 2.0, 1.0)


def snap(*, can=None, tools=None, pressure=None, load1=0.5, cores=10, avail=12.0, restrictions=None):
    out = {"specs": {"cores": cores, "mem_total_gb": 16.0, "os": "Darwin 25.5.0", "arch": "arm64"},
           "load": {"cores": cores, "load_1": load1, "mem_total_gb": 16.0, "mem_available_gb": avail, "disk_free_gb": 200.0},
           "battery": {"present": False, "on_battery": False}, "toolchain": tools if tools is not None else {},
           "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "restrictions": restrictions or {}}
    if can is not None:
        out["can"] = can
    if pressure is not None:
        out["pressure"] = pressure
    return out


def mach(label, snapshot, *, is_self=False, home=False):
    return rule.MachineInput(label, label, snapshot, True, is_self, home, True, 0)


def best_of_five(fn):
    runs = []
    for _ in range(5):
        t = time.perf_counter()
        fn()
        runs.append(time.perf_counter() - t)
    return min(runs)


def test_a_need_is_met_only_by_a_positive_report():
    ffmpeg = N.parse_need("ffmpeg")
    assert N.meets(snap(can={"tools": {"ffmpeg": True}}), ffmpeg) is True
    assert N.meets(snap(can={"tools": {"ffmpeg": False}}), ffmpeg) is False
    assert N.meets(snap(can={"tools": {}}), ffmpeg) is None
    assert N.meets(None, ffmpeg) is None
    got = rule.decide([mach("a", snap(can={"tools": {}}))], BUILD, needs=["ffmpeg"])
    assert got.chosen is None and "has not reported whether it has ffmpeg" in got.reason and "a:" in got.reason


def test_an_old_peer_without_a_can_block_falls_back_to_its_toolchain_and_says_it_needs_an_update():
    old = snap(tools={"ffmpeg": True, "node": False})
    assert N.meets(old, N.parse_need("ffmpeg")) is True and N.meets(old, N.parse_need("node")) is False
    assert N.meets(old, N.parse_need("xcode")) is None
    got = rule.decide([mach("tower", old)], BUILD, needs=[N.parse_need("xcode")])
    assert "has not reported whether it has xcode (needs an app update)" in got.candidates[0]["filter"]
    assert got.candidates[0]["needs_unmet"]


def test_gpu_vram_label_os_and_the_rest_of_the_vocabulary():
    can = {"tools": {}, "xcode": "16.1", "ios_sim": False, "labels": ["4090"], "cores": 24, "mem_gb": 64,
           "gpus": [{"vendor": "nvidia", "model": "rtx 4090", "vram_gb": 24, "discrete": True}]}
    s = snap(can=can)
    for word, want in (("gpu", True), ("gpu:nvidia", True), ("cuda", True), ("gpu:amd", False), ("gpu:apple", False),
                       ("vram_gb>=24", True), ("vram_gb>=32", False), ("mem_gb>=32", True), ("mem_gb>=128", False), ("cores>=24", True),
                       ("disk_gb>=100", True), ("disk_gb>=500", False), ("label:4090", True), ("label:other", False), ("os:macos", True),
                       ("os:linux", False), ("arch:arm64", True), ("xcode", True), ("ios_sim", False)):
        assert N.meets(s, N.parse_need(word)) is want, word
    assert N.meets(snap(can={"tools": {}, "gpus": []}), N.parse_need("gpu")) is False
    assert N.meets(snap(can={"tools": {}}), N.parse_need("gpu")) is None
    assert N.meets(snap(can={"tools": {}, "xcode": None}), N.parse_need("xcode")) is False


def test_an_unknown_word_is_refused_naming_the_known_words():
    for bad in ("pytest", "vram_gb>=abc", "os:beos", "label:", "gpu:"):
        with pytest.raises(ValueError, match="known words"):
            N.parse_need(bad)
    with pytest.raises(ValueError):
        N.parse_all(["ffmpeg"] * 9)
    assert N.parse_all(["ffmpeg", "FFMPEG"]) == [N.Need("tool", "ffmpeg")]


def test_from_command_reads_program_names_without_running_them():
    strict, filters, prefs = N.from_command("npx playwright test && ffmpeg -i a b")
    assert [n.text for n in strict] == ["node", "ffmpeg"] and [n.text for n in filters] == ["playwright_browsers"] and prefs == []
    assert [n.text for n in N.from_command("FOO=1 time nice -n 5 xcodebuild -scheme x | tee log; docker ps")[0]] == ["xcode", "docker"]
    assert N.from_command("echo 'unbalanced && ffmpeg") == ([], [], [])
    assert N.from_command("pytest -q") == ([], [], [])
    assert [n.text for n in N.from_command("/usr/bin/python3.12 -m pytest")[0]] == ["python3.12"]


def test_kind_defaults_are_filters_for_browser_and_preferences_for_render():
    assert [n.text for n in N.kind_defaults("browser")[0]] == ["playwright_browsers"] and N.kind_defaults("browser")[1] == []
    assert [n.text for n in N.kind_defaults("render")[1]] == ["gpu", "ffmpeg"] and N.kind_defaults("render")[0] == []
    assert N.kind_defaults("suite") == ([], [])


def test_a_pegged_peer_is_refused_even_when_its_figures_say_room_and_names_why():
    pegged = snap(pressure={"pegged": True, "why": "busy cores 9.4 over its line 9", "mem": "normal"})
    got = rule.decide([mach("b", pegged), mach("c", snap(pressure={"pegged": False, "mem": "normal"}))], BUILD)
    assert got.chosen == "c"
    row = next(r for r in got.candidates if r["label"] == "b")
    assert row["filter"] == "it is pegged: busy cores 9.4 over its line 9"
    assert rule.decide([mach("b", pegged)], BUILD).chosen is None
    assert rule.decide([mach("b", pegged, home=True)], Workload("light")).chosen is None


def test_memory_pressure_is_a_filter_and_a_missing_or_odd_block_is_not_pegged():
    assert "memory pressure (critical)" in rule.decide([mach("b", snap(pressure={"mem": "critical"}))], BUILD).reason
    assert rule.decide([mach("b", snap(pressure={"mem": "normal"}))], BUILD).chosen == "b"
    for odd in (None, "x", [], {"pegged": "yes"}, {"held": "x"}):
        s = snap()
        if odd is not None:
            s["pressure"] = odd
        assert rule.decide([mach("b", s)], BUILD).chosen == "b"


def test_headroom_subtracts_what_is_held():
    plain = rule.headroom(snap())
    held = rule.headroom(snap(pressure={"held": {"cpu": 3.0, "ram_gb": 4.0, "n": 2}}))
    assert plain.cpu_cores - held.cpu_cores == pytest.approx(3.0) and plain.mem_gb - held.mem_gb == pytest.approx(4.0)
    big = Workload("suite", 7.0, 2.0, 1.0)
    assert rule.decide([mach("b", snap())], big).chosen == "b"
    assert rule.decide([mach("b", snap(pressure={"held": {"cpu": 3.0, "ram_gb": 0.0, "n": 1}}))], big).chosen is None


def test_preferences_order_candidates_and_never_add_or_remove_one():
    plain, gpu = snap(can={"tools": {}, "gpus": []}), snap(can={"tools": {}, "gpus": [{"vendor": "nvidia", "discrete": True}]},
                                                           load1=4.0)
    ms = [mach("plain", plain), mach("gpu", gpu)]
    assert rule.decide(ms, BUILD).chosen == "plain"
    got = rule.decide(ms, BUILD, prefer=[N.parse_need("gpu")])
    assert got.chosen == "gpu" and {r["label"]: r["prefer_met"] for r in got.candidates} == {"plain": 0, "gpu": 1}
    assert rule.decide([mach("plain", plain)], BUILD, prefer=[N.parse_need("gpu")]).chosen == "plain"
    assert sum(r["candidate"] for r in rule.decide(ms, BUILD, prefer=[N.parse_need("label:x")]).candidates) == 2


def test_a_word_outside_the_vocabulary_from_an_old_caller_is_a_toolchain_name():
    s = snap(tools={"pytest": True})
    assert rule.decide([mach("a", s)], BUILD, needs=["pytest"]).chosen == "a"
    assert rule.decide([mach("a", snap(tools={"pytest": False}))], BUILD, needs=["pytest"]).chosen is None


def test_thirty_machines_decide_fast():
    ms = [mach(f"m{i}", snap(can={"tools": {"ffmpeg": i % 2 == 0}, "labels": ["x"]}, load1=i / 10)) for i in range(30)]
    need = [N.parse_need("ffmpeg"), N.parse_need("label:x")]
    got = rule.decide(ms, BUILD, needs=need, prefer=[N.parse_need("mem_gb>=8")])
    assert got.chosen and sum(r["candidate"] for r in got.candidates) == 15
    assert best_of_five(lambda: rule.decide(ms, BUILD, needs=need, prefer=need)) < 0.05


def test_the_explain_route_validates_needs_and_prefer_and_names_the_known_words():
    from src.api import pack_placement_routes as routes

    for field in ("needs", "prefer"):
        body = routes.ExplainBody(**{field: ["nonsense"]})
        with pytest.raises(HTTPException) as err:
            asyncio.run(routes.placement_explain(body, None))
        assert err.value.status_code == 422 and "ffmpeg" in err.value.detail["detail"] and err.value.detail["code"] == "need_unknown"


def test_the_tool_word_lists_of_the_rule_and_the_block_cannot_drift() -> None:
    from src.core.pack.machines import can_block
    assert set(N.TOOLS) == set(can_block.VOCAB)
