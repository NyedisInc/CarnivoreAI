
from __future__ import annotations

from src.core.inventory.plan_refs import plan_slugs


def test_a_plan_under_the_home_is_found_once() -> None:
    line = b'{"a":"/h/.claude/plans/fix-it.md","b":"see /h/.claude/plans/fix-it.md again"}'
    assert plan_slugs(line, ["/h/.claude"]) == ["fix-it"]


def test_an_escaped_slash_is_read() -> None:
    assert plan_slugs(b'{"p":"\\/h\\/.claude\\/plans\\/x_1.md"}', ["/h/.claude/"]) == ["x_1"]


def test_a_plans_folder_elsewhere_is_ignored() -> None:
    line = b'{"p":"/work/proj/plans/notes.md","q":"/h/.claude/plans/notes.mdx","r":"/h/.claude/plans/a.b.md"}'
    assert plan_slugs(line, ["/h/.claude"]) == ["a.b"]


def test_every_home_is_searched() -> None:
    line = b'{"p":"/h/.claude/plans/one.md","q":"/h/.claude-2/plans/two.md"}'
    assert plan_slugs(line, ["/h/.claude", "/h/.claude-2"]) == ["one", "two"]
