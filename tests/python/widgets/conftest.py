
from __future__ import annotations

import pytest

from scripts.widgets import harness


@pytest.fixture(scope="module")
def page_and_base():
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed in this venv")
    if not (harness.WEB / "node_modules").is_dir():
        pytest.skip("web/node_modules is missing: the harness cannot be built (npm ci in web/)")
    try:
        harness.build_harness()
    except harness.HarnessError as exc:
        pytest.skip(f"the widget harness did not build: {exc}")
    httpd, base = harness.serve()
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(args=harness.CHROMIUM_ARGS)
        except Exception as exc:
            httpd.shutdown()
            pytest.skip(f"no Playwright chromium here ({str(exc).splitlines()[0]}): "
                        "venv/bin/python3 -m playwright install chromium-headless-shell")
        page = browser.new_page(reduced_motion="reduce", timezone_id="UTC", locale="en-US")
        yield page, base
        browser.close()
    httpd.shutdown()
