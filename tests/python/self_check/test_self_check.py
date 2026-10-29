
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Iterator, List, Optional, Tuple

from src.core.self_check import constants as K
from src.core.self_check import monitor
from src.core.self_check.checks import Context, SystemIO, run_checks
from src.core.tmux_socket_resolution import resolve_probe_socket

ROOT = Path("/fake")
GOOD_STAT = SimpleNamespace(st_flags=0, st_dev=1)
DATALESS_STAT = SimpleNamespace(st_flags=K.SF_DATALESS, st_dev=1)
CTX = Context(code_dir=ROOT / "code", claude_dir=ROOT / ".claude", state_dir=ROOT / "state",
              db_file=ROOT / "state" / "cloude.db", resolve_socket=lambda lister: lister("carnivore"), tmux_path="/bin/tmux",
              claude_candidates=("/fake/claude",))


class FakeIO(SystemIO):

    def __init__(self) -> None:
        self.stats: Dict[Path, object] = {}
        for path, _ in CTX.critical:
            self.stats[path] = GOOD_STAT
        self.free = 50 * 1024 ** 3
        self.tmux: Optional[Tuple[int, str, str]] = (0, "cloude_a\n", "")
        self.live = 0
        self.probed: List[str] = []
        self.listable = True

    def stat(self, path: Path):
        return self.stats.get(path)

    def entries(self, path: Path) -> Iterator[Tuple[str, object]]:
        yield "a.jsonl", self.stats.get(path / "a.jsonl", GOOD_STAT)

    def list_dir(self, path: Path) -> None:
        if not self.listable:
            raise PermissionError(1, "Operation not permitted")

    def free_bytes(self, path: Path) -> int:
        return self.free

    def is_executable(self, path: str) -> bool:
        return path == "/fake/claude"

    def tmux_list(self, argv: List[str]):
        self.probed.append(argv[argv.index("-L") + 1])
        return self.tmux

    def live_session_count(self, db_file: Path) -> int:
        return self.live


def statuses(io: FakeIO) -> Dict[str, str]:
    return {r.name: r.status for r in run_checks(CTX, io)}


def test_clean_host_passes_every_check() -> None:
    assert statuses(FakeIO()) == {name: K.PASS for name in K.ALL_CHECKS}


def test_dataless_file_fails_files_and_raises_one_alert_only_on_change(monkeypatch) -> None:
    io = FakeIO()
    io.stats[CTX.claude_dir / "settings.json"] = DATALESS_STAT
    io.stats[CTX.claude_dir / "projects" / "a.jsonl"] = DATALESS_STAT
    files = run_checks(CTX, io)[0]
    assert files.status == K.FAIL
    assert any("settings.json" in f for f in files.findings) and any("a.jsonl" in f for f in files.findings)

    raised: List[str] = []
    resolved: List[str] = []
    monkeypatch.setattr(monitor.service, "raise_alert", lambda key, **kw: raised.append(key))
    monkeypatch.setattr(monitor.service, "resolve", lambda key, **kw: resolved.append(key))
    monitor.uninstall()
    monitor.apply(run_checks(CTX, io))
    monitor.apply(run_checks(CTX, io))
    assert raised == ["self_check.files"]
    io.stats[CTX.claude_dir / "settings.json"] = GOOD_STAT
    io.stats[CTX.claude_dir / "projects" / "a.jsonl"] = GOOD_STAT
    monitor.apply(run_checks(CTX, io))
    assert "self_check.files" in resolved and raised == ["self_check.files"]
    monitor.uninstall()


def tmux_status(ctx: Context, io: FakeIO):
    return next(r for r in run_checks(ctx, io) if r.name == K.CHECK_TMUX)


def test_probes_the_resolved_legacy_socket_and_no_server_with_live_sessions_fails() -> None:
    legacy = Context(**{**CTX.__dict__, "resolve_socket": lambda lister: resolve_probe_socket(
        SimpleNamespace(), None, lister)})
    io = FakeIO()
    io.tmux = (1, "", "no server running on /tmp/tmux-501/carnivore")
    io.live = 0
    assert tmux_status(legacy, io).status == K.PASS
    assert io.probed[:2] == ["carnivore", "cloude"]

    io.live = 3
    red = tmux_status(legacy, io)
    assert red.status == K.FAIL and "3 running" in red.findings[0]

    pinned = Context(**{**CTX.__dict__, "resolve_socket": lambda lister: lister("cloude")})
    io2 = FakeIO()
    tmux_status(pinned, io2)
    assert io2.probed == ["cloude"]
