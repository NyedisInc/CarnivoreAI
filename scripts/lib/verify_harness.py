
from __future__ import annotations

import json
import subprocess
import urllib.request
from typing import Any, Callable, Protocol


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
