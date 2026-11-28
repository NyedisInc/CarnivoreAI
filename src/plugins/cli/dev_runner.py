
from __future__ import annotations

import os
import signal
import sys
import threading
import time
import urllib.error
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from src.plugins.cli import checker
from src.plugins.cli.auth_discovery import CliAuthError, CliHttpClient
from src.plugins.host.sideload_copy import DEV_SKIP_DIRS

DEBOUNCE_MS_DEFAULT = 25
RENEW_INTERVAL_S = 20.0
LEASE_TTL_S = 60.0


def snapshot_tree(folder: Path) -> Dict[str, Tuple[int, int]]:
    snap: Dict[str, Tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in DEV_SKIP_DIRS)
        for fname in sorted(filenames):
            if fname == ".DS_Store" or fname.startswith("._") or fname.endswith((".pyc", ".pyo")):
                continue
            full = Path(dirpath) / fname
            try:
                st = os.lstat(full)
            except OSError:
                continue
            snap[full.relative_to(folder).as_posix()] = (st.st_mtime_ns, st.st_size)
    return snap


def _print_err(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _print_out(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _ensure_initial_sync(client: CliHttpClient, folder: Path, plugin_id: str) -> Optional[str]:
    status_code, row = client.request("GET", f"/api/v1/cplugs/{plugin_id}")
    if status_code == 404:
        sc, synced = client.request("POST", "/api/v1/cplug-owner/sideload", json_body={"path": str(folder)})
        if sc >= 400:
            detail = synced.get("detail", synced) if isinstance(synced, dict) else synced
            return f"initial sideload sync failed ({sc}): {detail}"
        if isinstance(synced, dict) and synced.get("needs_approval"):
            return f"{plugin_id} synced; approve and enable it once in Carnivore UI before starting dev mode"
        status_code, row = client.request("GET", f"/api/v1/cplugs/{plugin_id}")

    if status_code >= 400:
        detail = row.get("detail", row) if isinstance(row, dict) else row
        return f"could not query plugin {plugin_id} ({status_code}): {detail}"

    if isinstance(row, dict):
        if not row.get("enabled") or row.get("state") == "needs_approval":
            return f"{plugin_id} requires initial enable/consent in Carnivore UI before starting dev mode"
    return None


def run_dev(
    folder: Path,
    *,
    client: Optional[CliHttpClient] = None,
    debounce_ms: int = DEBOUNCE_MS_DEFAULT,
    on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    max_reloads: Optional[int] = None,
) -> int:
    folder = folder.resolve()
    report = checker.check_folder(folder)
    if not report.ok:
        for err in report.errors:
            _print_err(f"error: {err}")
        return 1

    plugin_id = report.manifest_v2.id if report.manifest_v2 is not None else folder.name
    if client is None:
        client = CliHttpClient()

    try:
        err_msg = _ensure_initial_sync(client, folder, plugin_id)
    except CliAuthError as exc:
        _print_err(f"plugin dev auth failed: {exc}")
        return 2
    if err_msg:
        _print_err(f"plugin dev: {err_msg}")
        return 2

    sc, lease = client.request(
        "POST",
        "/api/v1/cplug-owner/dev/lease",
        json_body={"path": str(folder), "ttl_seconds": LEASE_TTL_S},
    )
    if sc >= 400:
        detail = lease.get("detail", lease) if isinstance(lease, dict) else lease
        _print_err(f"plugin dev: failed to acquire dev trust lease ({sc}): {detail}")
        return 2

    lease_token = lease.get("lease_token") if isinstance(lease, dict) else None
    stop_event = threading.Event()

    def _renew_loop() -> None:
        while not stop_event.wait(RENEW_INTERVAL_S):
            try:
                sc_ren, _ = client.request(
                    "PUT",
                    f"/api/v1/cplug-owner/dev/lease/{plugin_id}",
                    json_body={"lease_token": lease_token, "ttl_seconds": LEASE_TTL_S},
                    timeout=5.0,
                )
                if sc_ren == 404:
                    stop_event.set()
                    return
            except (CliAuthError, OSError, urllib.error.URLError, ValueError) as exc:
                _print_err(f"[{plugin_id} lease renew failed ({type(exc).__name__})]: {exc}")

    def _sse_loop() -> None:
        last_seq = 0
        while not stop_event.is_set():
            try:
                for ev_name, payload in client.stream_sse(
                    f"/api/v1/cplug-owner/dev/stream/{plugin_id}?after_seq={last_seq}",
                    timeout=30.0,
                ):
                    if stop_event.is_set():
                        return
                    seq = payload.get("seq")
                    if isinstance(seq, int) and seq > last_seq:
                        last_seq = seq
                    if on_event is not None:
                        on_event(ev_name, payload)
                    if ev_name == "stderr":
                        _print_err(f"[{plugin_id} stderr] {payload.get('data', {}).get('text', '')}")
                    elif ev_name == "ui_error":
                        _print_err(f"[{plugin_id} ui_error] {payload.get('data', {})}")
                    elif ev_name == "permission_widened":
                        _print_err(f"[{plugin_id} permission_widened] re-consent required in Carnivore UI")
            except Exception:  # noqa: BLE001
                if stop_event.wait(0.5):
                    return

    renew_thread = threading.Thread(target=_renew_loop, daemon=True)
    sse_thread = threading.Thread(target=_sse_loop, daemon=True)
    on_main_thread = threading.current_thread() is threading.main_thread()
    prev_sigint: Any = None
    prev_sigterm: Any = None

    def _handle_sig(_signum: int, _frame: Any) -> None:
        stop_event.set()

    debounce_s = max(0.02, min(0.05, debounce_ms / 1000.0))
    pending_since: Optional[float] = None
    reloads = 0

    try:
        if on_main_thread:
            prev_sigint = signal.getsignal(signal.SIGINT)
            prev_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGINT, _handle_sig)
            signal.signal(signal.SIGTERM, _handle_sig)
        renew_thread.start()
        sse_thread.start()
        last_snap = snapshot_tree(folder)
        _print_out(f"dev lease acquired for {plugin_id} ({folder}); watching for changes...")
        while not stop_event.is_set():
            time.sleep(debounce_s)
            cur = snapshot_tree(folder)
            if cur != last_snap:
                last_snap = cur
                pending_since = time.monotonic()
                continue
            if pending_since is not None and (time.monotonic() - pending_since) >= debounce_s:
                pending_since = None
                rc, body = client.request(
                    "POST",
                    "/api/v1/cplug-owner/dev/reload",
                    json_body={"path": str(folder), "probe_ui": True},
                    timeout=15.0,
                )
                if rc == 409:
                    detail = body.get("detail", body) if isinstance(body, dict) else body
                    _print_err(f"reload halted ({detail})")
                    return 1
                if rc >= 400:
                    _print_err(f"reload error ({rc}): {body}")
                else:
                    timings = body.get("timings", {}) if isinstance(body, dict) else {}
                    _print_out(
                        f"reloaded {plugin_id}: status={body.get('status')} total_ms={timings.get('total_ms')}"
                    )
                    reloads += 1
                    if max_reloads is not None and reloads >= max_reloads:
                        break
    finally:
        stop_event.set()
        if on_main_thread and prev_sigint is not None:
            signal.signal(signal.SIGINT, prev_sigint)
        if on_main_thread and prev_sigterm is not None:
            signal.signal(signal.SIGTERM, prev_sigterm)
        renew_thread.join(timeout=1.0)
        try:
            client.request("DELETE", f"/api/v1/cplug-owner/dev/lease/{plugin_id}", timeout=5.0)
        except Exception:  # noqa: BLE001
            pass
    return 0
