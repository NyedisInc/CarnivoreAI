
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "web"
BUILD_DIR = REPO / "client" / "widget-harness-build"
PAGE = "/static/widget-harness-build/index.html"
HARNESS_CONFIG = "vite.widget-harness.config.ts"

CHROMIUM_ARGS = ["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--use-mock-keychain",
                 "--font-render-hinting=none"]

READY_TIMEOUT_MS = 30_000


class HarnessError(Exception):
    pass


@dataclass
class Render:

    key: str
    zone: str
    size: str
    fixture: str
    theme: str
    findings: list[dict] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)
    error: str = ""
    shot: Path | None = None
    console: list[str] = field(default_factory=list)


RESOURCE_NOISE = "Failed to load resource"


def watch_console(page: Any) -> list[str]:
    existing = getattr(page, "_lab_console", None)
    if existing is not None:
        return existing
    seen: list[str] = []

    def on_console(message: Any) -> None:
        if message.type == "error" and RESOURCE_NOISE not in message.text:
            seen.append(message.text[:300])

    page.on("console", on_console)
    page.on("pageerror", lambda exc: seen.append(f"uncaught: {str(exc)[:300]}"))
    page._lab_console = seen
    return seen


def drain_console(page: Any) -> list[str]:
    seen = watch_console(page)
    out = list(dict.fromkeys(seen))
    seen.clear()
    return out


def build_harness() -> None:
    if not (WEB / "node_modules").is_dir():
        raise HarnessError("web/node_modules is missing: run `npm ci` in web/")
    done = subprocess.run(["npx", "vite", "build", "--config", HARNESS_CONFIG], cwd=WEB,
                          capture_output=True, text=True, timeout=600)
    if done.returncode != 0 or not (BUILD_DIR / "index.html").is_file():
        tail = (done.stderr or done.stdout).strip().splitlines()[-5:]
        raise HarnessError("harness build failed: " + " | ".join(tail))


SOURCE_ROOTS = (WEB / "src", WEB / HARNESS_CONFIG)
SOURCE_SUFFIXES = {".ts", ".svelte", ".css", ".html", ".js", ".json"}


def harness_is_stale() -> bool:
    built = BUILD_DIR / "index.html"
    if not built.is_file():
        return True
    built_at = built.stat().st_mtime
    for root in SOURCE_ROOTS:
        files = [root] if root.is_file() else (p for p in root.rglob("*") if p.suffix in SOURCE_SUFFIXES)
        if any(p.stat().st_mtime > built_at for p in files):
            return True
    return False


def build_if_stale() -> bool:
    if not harness_is_stale():
        return False
    build_harness()
    return True


def serve() -> tuple[Any, str]:
    from scripts.lib_csp_static_server import serve as csp_serve  # noqa: PLC0415

    httpd, port = csp_serve(REPO)
    return httpd, f"http://127.0.0.1:{port}"


def wait_ready(page: Any) -> None:
    try:
        page.wait_for_function("() => window.__widgetHarness && window.__widgetHarness.ready === true",
                               timeout=READY_TIMEOUT_MS)
    except Exception as exc:
        raise HarnessError(f"the harness never said ready: {str(exc).splitlines()[0]}") from None


def catalog(page: Any, base: str) -> tuple[list[dict], list[str]]:
    watch_console(page)
    page.goto(f"{base}{PAGE}?list=1")
    wait_ready(page)
    widgets = page.evaluate("() => window.__widgetHarness.catalog")
    themes = page.evaluate("() => window.__widgetHarness.themes")
    if not widgets:
        raise HarnessError("the harness published an empty catalog")
    return widgets, themes


def open_widget(page: Any, base: str, key: str, fixture: str, first: dict, *, extra: dict | None = None,
                scenario: str | None = None) -> Render:
    from urllib.parse import urlencode  # noqa: PLC0415

    watch_console(page)
    query = {"widget": key, "fixture": fixture, **first, **(extra or {})}
    if scenario is not None:
        query["scenario"] = "wait"
    page.goto(f"{base}{PAGE}?{urlencode(query)}")
    if scenario is not None:
        page.evaluate("(text) => window.__widgetHarness.provideScenario(text)", scenario)
    wait_ready(page)
    return Render(key=key, fixture=fixture, error=page.evaluate("() => window.__widgetHarness.error"),
                  console=drain_console(page), **first)


JUNK = re.compile(
    r"\b(?:unknown|undefined|null|NaN)\b|\[object Object\]|\bcloude_[\w-]+|\bses_\w+|\badopted:"
    r"|/Users/|/home/|/Volumes/|\b\d{1,3}(?:\.\d{1,3}){3}\b|\b[\w-]+\.(?:local|home|lan)\b"
    r"|\b[A-Za-z0-9_-]{32,}\b|\b(?:sk|ghp|xox[bp])-[\w-]+",
    re.IGNORECASE,
)


def junk_findings(text: str) -> list[dict]:
    found = []
    for line in dict.fromkeys(text.splitlines()):
        hit = JUNK.search(line)
        if hit:
            found.append({"rule": "junk-text", "selector": "(cell text)", "px": 0,
                          "detail": f'shows "{hit.group(0)}" in "{line.strip()[:60]}"'})
    return found


def show(page: Any, key: str, fixture: str, zone: str, size: str, theme: str) -> Render:
    result = page.evaluate("(r) => window.__widgetHarness.show(r)", {"zone": zone, "size": size, "theme": theme})
    ready = page.evaluate("() => window.__widgetHarness.ready === true")
    return Render(key=key, zone=zone, size=size, fixture=fixture, theme=theme,
                  findings=result["findings"] + junk_findings(result.get("text", "")), misses=result["misses"],
                  error=result["error"] or ("" if ready else "the harness is not ready after the draw"), console=drain_console(page))


def shoot(page: Any, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    page.locator(".wh-stage").screenshot(path=str(dest), animations="disabled")
    return dest


def defects(page: Any) -> dict:
    report = page.evaluate("() => window.__widgetHarness.defects()")
    if report is None:
        raise HarnessError("the harness drew no cell to check for layout defects")
    return report
