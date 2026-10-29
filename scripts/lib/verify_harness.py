
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import traceback
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from src.core import product_identity

EXIT_PASS, EXIT_FAIL, EXIT_CANNOT_DETERMINE = 0, 1, 2
EXIT_REFUSED = EXIT_CANNOT_DETERMINE
LIVE_PORT = 8000

LIVE_PORTS = (LIVE_PORT, 5000)


class LiveInstallRefused(RuntimeError):
    pass


class SupportsCheck(Protocol):

    def check(self, ok: bool, name: str, detail: str = "") -> Any: ...


def token_of(storage_state: str, base: str) -> str:
    with open(storage_state) as fh:
        state = json.load(fh)
    for origin in state.get("origins", []):
        if origin.get("origin") == base:
            for item in origin.get("localStorage", []):
                if item.get("name") == "claude_tunnel_token":
                    return item["value"]
    raise RuntimeError("no access token in the storage state")


def call(args, path: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(
        args.base + "/api/v1" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + token_of(args.storage_state, args.base)},
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read() or b"null")


def set_theme(args, theme: str | None) -> None:
    rev = call(args, "/preferences")["revision"]
    call(args, "/preferences", "PATCH", {"changes": {"theme": theme}, "expected_revision": rev})


def dismiss_offers(page) -> None:
    no = page.locator("#restore-offer-no")
    try:
        no.wait_for(state="visible", timeout=1500)
        no.click()
        page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001
        pass


def guarded(report: SupportsCheck, name: str, fn: Callable[[], Any], current: dict | None = None) -> None:
    if current is not None:
        current["check"] = name
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        report.check(False, f"{name}: the check could not run to the end", f"{type(exc).__name__}: {exc}")


def tmux(socket: str, *argv: str) -> str:
    return subprocess.run(["tmux", "-L", socket, *argv], capture_output=True, text=True,
                          timeout=10, check=False).stdout


def check(cond: bool, what: str, failures: list[str]) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


def live_target_refusal(args: Any) -> Optional[str]:
    try:
        require_slot(args)
    except LiveInstallRefused as exc:
        return str(exc)
    return None


def refuse_live_target(args: Any) -> Optional[int]:
    reason = live_target_refusal(args)
    if reason is None:
        return None
    print(f"CANNOT DETERMINE: {reason}")
    return EXIT_REFUSED


def live_state_roots() -> tuple[Path, ...]:
    support = Path.home() / "Library" / "Application Support"
    roots = [support / name for name in (product_identity.STATE_DIR_NAME, *product_identity.LEGACY_STATE_DIR_NAMES)]
    for var in ("CARNIVORE_STATE_DIR", "CLOUDE_STATE_DIR", "CLOUDECODE_STATE_DIR"):
        if os.environ.get(var):
            roots.append(Path(os.environ[var]).expanduser())
    return tuple(r.resolve() for r in roots)


def refuse_live(base: str | None = None, socket: str | None = None, *paths: str | None) -> None:
    live_sockets = (product_identity.TMUX_SOCKET_NAME, *product_identity.LEGACY_TMUX_SOCKET_NAMES)
    if socket in live_sockets:
        raise LiveInstallRefused(f"refusing the live tmux socket {socket!r}")
    if base and any(base.rstrip("/").endswith(f":{port}") for port in LIVE_PORTS):
        raise LiveInstallRefused(f"refusing the live install at {base}")
    roots = live_state_roots()
    for raw in paths:
        if not raw:
            continue
        target = Path(raw).expanduser().resolve()
        if any(target == root or root in target.parents for root in roots):
            raise LiveInstallRefused(f"refusing a path inside the live state directory: {target}")


def refuse_live_db_file(db: str) -> None:
    refuse_live(None, None, db)
    wal = Path(f"{db}-wal")
    if wal.exists() and wal.stat().st_size > 0:
        raise LiveInstallRefused(f"{db} has a live write-ahead log ({wal.name}); it is not a copy")


SLOT_ROOT = Path("~/dev-worktrees/.testsrv").expanduser()
BUSY_TIMEOUT_MS = 10_000


def slot_db(state_dir: str) -> sqlite3.Connection:
    refuse_live(None, None, state_dir)
    root = Path(state_dir).expanduser().resolve()
    if SLOT_ROOT.resolve() not in root.parents and root != SLOT_ROOT.resolve():
        raise LiveInstallRefused(f"{root} is not under a leased slot ({SLOT_ROOT})")
    for name in (product_identity.DB_FILENAME, *product_identity.LEGACY_DB_FILENAMES):
        if (root / name).exists():
            conn = sqlite3.connect(root / name, timeout=BUSY_TIMEOUT_MS / 1000)
            conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            return conn
    raise RuntimeError(f"no datastore under {root}")


def require_slot(args: Any) -> None:
    opts = vars(args)
    refuse_live(opts.get("base"), opts.get("socket"), opts.get("state_dir"), opts.get("db"))


def exit_code(passes: int, failures: int) -> int:
    if passes + failures == 0:
        return EXIT_CANNOT_DETERMINE
    return EXIT_FAIL if failures else EXIT_PASS


class CleanupLedger:

    def __init__(self, delete: Callable[[str], Any]) -> None:
        self._delete = delete
        self._paths: list[str] = []

    def record(self, path: str) -> str:
        self._paths.append(path)
        return path

    def run(self) -> list[str]:
        left: list[str] = []
        for path in reversed(self._paths):
            try:
                self._delete(path)
            except (OSError, ValueError) as exc:
                left.append(f"{path} ({type(exc).__name__}: {exc})")
        self._paths.clear()
        return left


OPENED_TMUX_JS = """async () => {
  const id = window.TerminalController && window.TerminalController._sessionId();
  if (!id) return null;
  const listed = await window.API.listSessions();
  const rows = Array.isArray(listed) ? listed : (listed.sessions || []);
  const hit = rows.find((r) => r.session && r.session.id === id);
  return hit ? (hit.tmux_session || null) : null;
}"""

_TERMINAL_STATE_JS = (
    "() => {const T=window.TerminalController;"
    "return {ws:T&&T.ws?T.ws.readyState:null, rows:T&&T.term?T.term.rows:null};}"
)


def wait_terminal_ready(page, tries: int = 60) -> bool:
    for _ in range(tries):
        page.wait_for_timeout(1000)
        state = page.evaluate(_TERMINAL_STATE_JS)
        if state.get("ws") == 1 and state.get("rows"):
            return True
    return False


def opened_tmux_name(page) -> str | None:
    name = page.evaluate(OPENED_TMUX_JS)
    return name if isinstance(name, str) and name else None


def harness_errors() -> tuple[type[BaseException], ...]:
    types: list[type[BaseException]] = [OSError, RuntimeError, ValueError, TimeoutError, subprocess.SubprocessError]
    try:
        from playwright.sync_api import Error as PlaywrightError
    except ImportError:
        pass
    else:
        types.append(PlaywrightError)
    return tuple(types)


def run_main(main: Callable[[], int]) -> int:
    try:
        return main()
    except harness_errors() as exc:
        traceback.print_exc(file=sys.stderr)
        print(f"CANNOT DETERMINE: the harness broke: {type(exc).__name__}: {exc}")
        return EXIT_CANNOT_DETERMINE
