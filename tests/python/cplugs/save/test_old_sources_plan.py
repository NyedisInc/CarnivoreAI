
from __future__ import annotations

from collections import Counter

from src.cplugs.save.vault import identity
from src.cplugs.save.vault.old_sources import labels, plan
from src.cplugs.save.vault.old_sources.attribution import NO_PROJECT_GROUP, Attributor
from tests.python.cplugs.save.old_sources_helpers import lines, make_copy

G, D, H, S, X, Y = ("11111111-0000-0000-0000-000000000001", "22222222-0000-0000-0000-000000000002",
                    "33333333-0000-0000-0000-000000000003", "44444444-0000-0000-0000-000000000004",
                    "55555555-0000-0000-0000-000000000005", "66666666-0000-0000-0000-000000000006")
E1, E2 = "-Users-x-one", "-Users-x-two"


def test_the_planner_files_one_current_copy_and_keeps_only_what_diverged() -> None:
    held_d = make_copy("held:vault", f"{E2}/{D}.jsonl", lines(10, "d") + b'{"kept":"in the vault"}\n', captured=1_700_000_500.0)
    held_h = make_copy("held:disk", f"{E1}/{H}.jsonl", lines(6, "h"), captured=1_700_000_100.0)
    sub_short, sub_long = lines(2, "s"), lines(4, "s")
    held_x = make_copy("held:vault", f"{E1}/{X}.jsonl", lines(4, "x"), captured=1_700_000_900.0)
    held_y = [make_copy("held:vault", f"{E1}/{Y}.jsonl", lines(5, "y"), captured=1_700_000_200.0),
              make_copy("held:vault", f"{E1}/{Y}/subagents/agent-9.jsonl", lines(2, "w"), captured=1_700_000_200.0)]
    old = [
        make_copy("archive:a", f"{E1}/{G}.jsonl", lines(3), 1_600_000_001.0), make_copy("archive:b", f"{E1}/{G}.jsonl", lines(5), 1_600_000_002.0),
        make_copy("archive:c", f"{E1}/{G}.jsonl", lines(9), 1_600_000_003.0), make_copy("oldstore", f"{E1}/{G}.jsonl", lines(9), 1_600_000_004.0),
        make_copy("archive:a", f"{E1}/{G}/subagents/agent-1.jsonl", sub_short, 1_600_000_001.0),
        make_copy("archive:c", f"{E1}/{G}/subagents/agent-1.jsonl", sub_long, 1_600_000_003.0),
        make_copy("archive:c", f"{E1}/{D}.jsonl", lines(10, "d") + b'{"removed":"line"}\n', 1_700_001_000.0),
        make_copy("archive:c", f"{E1}/{H}.jsonl", lines(6, "h"), 1_600_000_005.0),
        make_copy("archive:c", f"{E1}/{S}.jsonl", lines(4, "p"), 1_600_000_006.0),
        make_copy("swarmtar", f"{E2}/{S}.jsonl", lines(4, "q"), 1_600_000_007.0),
        make_copy("archive:c", f"{E1}/agent-abc1234.jsonl", lines(2, "z"), 1_600_000_008.0),
        make_copy("archive:c", f"{E1}/{X}.jsonl", lines(7, "x"), 1_800_000_000.0),
        make_copy("archive:a", f"{E1}/{Y}/subagents/agent-9.jsonl", lines(1, "w"), 1_600_000_009.0),
        make_copy("archive:c", f"{E1}/{Y}/subagents/agent-9.jsonl", lines(2, "w"), 1_600_000_010.0),
    ]
    book = labels.LabelBook(by_conv={G: ["junk-20260930:trivial"]})
    result = plan.plan_sources(old, [held_d, held_h, held_x, *held_y], book, Attributor(identity.ProjectIndex()))
    by_unit = {(p.unit, p.kind): p for p in result.points}
    split = next(u for u, _k in by_unit if u.startswith(S + "@"))
    assert sorted(by_unit) == sorted([(G, "current"), (D, "kept"), (X, "kept"), (S, "current"), (split, "current"), ("agent-abc1234", "current")])
    assert [f.rel.rsplit("/", 1)[-1] for f in by_unit[(G, "current")].files] == [f"{G}.jsonl", "agent-1.jsonl"]
    assert by_unit[(G, "current")].files[0].copy.length == len(lines(9)) and by_unit[(G, "current")].stamp == 1_600_000_004.0
    assert by_unit[(D, "kept")].stamp == 1_700_000_499.0
    assert by_unit[(D, "kept")].tags["captured_epoch"] == 1_700_001_000.0
    assert by_unit[(X, "kept")].stamp == 1_700_000_899.0 and Y not in {p.unit for p in result.points}
    assert by_unit[(G, "current")].tags["labels"] == ["junk-20260930:trivial"] and by_unit[(G, "current")].tags["group"] == NO_PROJECT_GROUP
    counts = Counter(d.decision for d in result.decisions)
    assert counts == {plan.COVERED: 4, plan.CURRENT: 5, plan.SAME_AS_IMPORT: 1, plan.KEPT: 2, plan.HELD: 2}
    assert H not in {p.unit for p in result.points} and len(result.decisions) == len(old)


def test_a_held_copy_inside_a_container_folder_is_still_held() -> None:
    z = "77777777-0000-0000-0000-000000000007"
    held = make_copy("held:vault", f"projects/_hold-for-archive/{E1}/{z}.jsonl", lines(5, "z"), captured=1_700_000_000.0)
    old = [make_copy("oldstore", f"{E1}/{z}.jsonl", lines(5, "z"), 1_600_000_000.0)]
    result = plan.plan_sources(old, [held], labels.LabelBook(), Attributor(identity.ProjectIndex()))
    assert result.points == [] and [d.decision for d in result.decisions] == [plan.HELD]
