
from __future__ import annotations

import json
from pathlib import Path

from src.core.pack.globalsync import apply as gs_apply, collect, deps, rules
from src.core.pack.globalsync.store import Status

PKG = json.dumps({"name": "x", "dependencies": {"left-pad": "1.0.0"}})


def make_main(tmp: Path, lock: str = "lock-v1") -> Path:
    home = tmp / "main"
    skill = home / ".claude" / "skills" / "extract-alpha"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("skill\n")
    (skill / "package.json").write_text(PKG)
    (skill / "package-lock.json").write_text(lock)
    cache = home / ".claude" / "plugins" / "cache"
    (cache / "temp_git_1792206295412_x678fn").mkdir(parents=True)
    (cache / "temp_git_1792206295412_x678fn" / "p.json").write_text("{}")
    (cache / "real").mkdir()
    (cache / "real" / "p.json").write_text("{}")
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text("{}")
    bundled = home / ".codex" / "plugins" / "cache" / "openai-bundled" / "browser"
    bundled.mkdir(parents=True)
    (bundled / "plugin.json").write_text("{}")
    (home / ".codex" / "AGENTS.md").write_text("rules\n")
    return home


def bundle(home: Path, out: Path) -> Path:
    return collect.build(collect.slots_for(home, [], ["claude", "codex"]), out, home).path


class Runner:

    def __init__(self, code: int = 0) -> None:
        self.calls, self.code = [], code

    def __call__(self, cmd, cwd, timeout):
        self.calls.append((list(cmd), cwd))
        if self.code == 0:
            (Path(cwd) / "node_modules").mkdir(exist_ok=True)
        return self.code


def receive(tmp: Path, main: Path, name: str, member: Path):
    report = gs_apply.apply_bundle(bundle(main, tmp / name), home=member, accounts_root=member / ".carnivore" / "accounts", accounts=[],
                                   state=gs_apply.State(tmp / "applied.json"), backups=tmp / "bk", stage_root=tmp)
    return report


def install(tmp: Path, report, runner: Runner, which=lambda tool: f"/bin/{tool}"):
    return deps.install_applied(report.targets, deps.InstallState(tmp / "inst.json"), Status(tmp / "inst-status.json"), runner=runner, which=which)


def test_install_once_per_lockfile_and_again_when_it_changes(tmp_path):
    member, main = tmp_path / "member", make_main(tmp_path)
    member.mkdir()
    runner = Runner()
    folder = member / ".claude" / "skills" / "extract-alpha"
    assert install(tmp_path, receive(tmp_path, main, "b1.tgz", member), runner) == {str(folder): "installed"}
    assert runner.calls == [(["/bin/npm", "ci"], str(folder))]
    assert install(tmp_path, receive(tmp_path, main, "b2.tgz", member), runner) == {str(folder): "unchanged"}
    assert len(runner.calls) == 1
    (main / ".claude" / "skills" / "extract-alpha" / "package-lock.json").write_text("lock-v2")
    assert install(tmp_path, receive(tmp_path, main, "b3.tgz", member), runner) == {str(folder): "installed"}
    assert len(runner.calls) == 2
    assert Status(tmp_path / "inst-status.json").get(str(folder))["state"] == "installed"


def test_no_lockfile_uses_npm_install_missing_tool_is_needs_install_failure_retries(tmp_path):
    member, main = tmp_path / "member", make_main(tmp_path)
    member.mkdir()
    (main / ".claude" / "skills" / "extract-alpha" / "package-lock.json").unlink()
    folder = member / ".claude" / "skills" / "extract-alpha"
    report = receive(tmp_path, main, "b1.tgz", member)
    assert install(tmp_path, report, Runner(), which=lambda tool: None) == {str(folder): "needs install"}
    bad = Runner(code=1)
    assert install(tmp_path, report, bad) == {str(folder): "failed"} and bad.calls[0][0] == ["/bin/npm", "install"]
    good = Runner()
    assert install(tmp_path, report, good) == {str(folder): "installed"}


def test_receivers_own_node_modules_is_a_baseline_not_replaced(tmp_path):
    member, main = tmp_path / "member", make_main(tmp_path)
    folder = member / ".claude" / "skills" / "extract-alpha"
    (folder / "node_modules" / "mine").mkdir(parents=True)
    runner = Runner()
    assert install(tmp_path, receive(tmp_path, main, "b1.tgz", member), runner) == {str(folder): "unchanged"}
    assert runner.calls == [] and (folder / "node_modules" / "mine").is_dir()


def test_receiver_owned_names_are_not_collected_and_an_apply_leaves_them_alone(tmp_path):
    main = make_main(tmp_path)
    with __import__("tarfile").open(bundle(main, tmp_path / "b.tgz"), "r:gz") as tar:
        names = tar.getnames()
    assert not any("temp_git_" in n or "openai-bundled" in n for n in names)
    assert any(n.endswith("plugins/cache/real/p.json") for n in names)
    assert rules.path_problem("claude", "plugins/cache/temp_git_1_x/p.json") and rules.path_problem("codex", "plugins/cache/openai-bundled/a") 
    member = tmp_path / "member"
    own = {".claude/skills/extract-alpha/node_modules/mine": "n", ".claude/skills/video-forge/.git/config": "g",
           ".codex/plugins/cache/openai-bundled/browser/plugin.json": "b", ".claude/plugins/cache/temp_git_9_z/p.json": "t"}
    for rel, text in own.items():
        (member / rel).parent.mkdir(parents=True, exist_ok=True)
        (member / rel).write_text(text)
    state = gs_apply.State(tmp_path / "applied.json")
    state.save({str(member / ".claude"): ["skills/video-forge/.git/config", "plugins/cache/temp_git_9_z/p.json"],
                str(member / ".codex"): ["plugins/cache/openai-bundled/browser/plugin.json"]})
    receive(tmp_path, main, "b2.tgz", member)
    receive(tmp_path, main, "b3.tgz", member)
    assert {rel: (member / rel).read_text() for rel in own} == own
