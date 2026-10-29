
from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_PERF = REPO_ROOT / "scripts" / "perf"
if str(SCRIPTS_PERF) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PERF))

requires_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")


@pytest.fixture()
def perf_server(request):
    from perf_env import PerfServer
    from tests.socket_guard import derive_test_socket

    server = PerfServer(tmux_socket_name=derive_test_socket(f"perf_{request.node.name[:20]}"))
    try:
        server.start()
        yield server
    finally:
        server.stop()


@requires_tmux
def test_isolated_server_boots_and_answers_health(perf_server) -> None:
    import httpx

    resp = httpx.get(f"{perf_server.base_url}/health", timeout=5.0)
    assert resp.status_code == 200
    assert perf_server.tmux_socket != "cloude"


@requires_tmux
def test_a_real_shell_session_can_be_created_and_listed(perf_server) -> None:
    from perf_client import PerfClient, wait_until

    client = PerfClient(perf_server.base_url, perf_server.totp_secret)
    try:
        client.login()
        body = client.create_session(perf_server.work_dir, "smoke-session")
        assert body["id"]

        found = wait_until(lambda: client.row_for(body["id"]) is not None, timeout=15.0)
        assert found, "the created session never appeared in /sessions/list"
    finally:
        client.close()


@requires_tmux
def test_one_keystroke_actually_paints_through_onrender(perf_server) -> None:
    playwright_module = pytest.importorskip(
        "playwright.sync_api",
        reason="playwright is not installed, so nothing about paint was measured",
    )

    import perf_browser
    from perf_client import PerfClient, wait_until

    client = PerfClient(perf_server.base_url, perf_server.totp_secret)
    try:
        client.login()
        client.mark_account_welcome_seen()
        session = client.create_session(perf_server.work_dir, "smoke-render")
        assert wait_until(lambda: client.row_for(session["id"]) is not None, timeout=15.0)

        with playwright_module.sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--use-mock-keychain"])
            try:
                context = browser.new_context(viewport={"width": 1024, "height": 768})
                perf_browser.install_instrumentation(context)
                page = context.new_page()
                perf_browser.inject_authenticated_session(
                    page, perf_server.base_url, client.token
                )
                page.wait_for_function(
                    "(sid) => !!document.querySelector('[data-session-id=\"' + sid + '\"]')",
                    arg=session["id"],
                    timeout=15000,
                )
                perf_browser.open_session_row(page, session["id"])

                samples = perf_browser.measure_typing_echo(page, count=1)
                assert samples["total"], "no render was ever observed for the keystroke"
                assert samples["total"][0] >= 0.0
            finally:
                browser.close()
    finally:
        client.close()
