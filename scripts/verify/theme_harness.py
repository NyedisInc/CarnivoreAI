#!/usr/bin/env python3

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
STATIC_SERVER = os.path.join(HERE, "_theme_effect_static_server.py")

UNSAFE_PORTS = frozenset({5060, 5061, 6000, 6665, 6666, 6667, 6668, 6669, 6697})
CHROMIUM_ARGS = ["--force-color-profile=srgb", "--disable-lcd-text",
                 "--hide-scrollbars", "--use-mock-keychain"]
VIEWPORT = {"width": 1280, "height": 800}


def check_port(port: int) -> bool:
    if port in UNSAFE_PORTS:
        print(f"port {port} is on Chromium's restricted list; pick another", file=sys.stderr)
        return False
    return True


def wait_for_server(port: int, timeout: float = 15) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"static server on port {port} never became ready")


def image_diff(png_a: bytes, png_b: bytes, box: dict[str, int] | None = None,
               with_changed_pct: bool = False) -> dict[str, float]:
    from PIL import Image, ImageChops
    img_a = Image.open(io.BytesIO(png_a)).convert("RGB")
    img_b = Image.open(io.BytesIO(png_b)).convert("RGB")
    if box is not None:
        crop = (box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"])
        img_a, img_b = img_a.crop(crop), img_b.crop(crop)
    delta = ImageChops.difference(img_a, img_b)
    bands = delta.split()
    npx = img_a.size[0] * img_a.size[1]
    mx = max(b.getextrema()[1] for b in bands)
    mean = sum(sum(i * c for i, c in enumerate(b.histogram())) for b in bands) / (3.0 * npx)
    out: dict[str, float] = {"max": mx, "mean": round(mean, 3)}
    if with_changed_pct:
        changed = sum(delta.convert("L").point(lambda v: 255 if v > 0 else 0).histogram()[255:])
        out["changedPct"] = round(100.0 * changed / npx, 2)
    return out


@contextmanager
def static_server(port: int) -> Iterator[str]:
    server = subprocess.Popen([sys.executable, STATIC_SERVER, str(port)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for_server(port)
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.terminate()


def run_theme_sweep(themes: list[str], port: int,
                    measure_one: Callable[[Any, str, str], dict[str, Any]],
                    finish_row: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                    ) -> list[dict[str, Any]] | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed for this interpreter. This is an instrument, "
              "not a runtime dependency: install it into a scratch environment "
              "(pip install playwright && playwright install chromium) and re-run.",
              file=sys.stderr)
        return None
    rows: list[dict[str, Any]] = []
    with static_server(port) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(args=CHROMIUM_ARGS)
        for theme in themes:
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1,
                                      reduced_motion="no-preference")
            try:
                row = measure_one(ctx.new_page(), base, theme)
            except Exception as exc:  # noqa: BLE001
                row = {"theme": theme, "error": f"{type(exc).__name__}: {exc}"}
            row = finish_row(row) if finish_row else row
            rows.append(row)
            print(json.dumps(row), flush=True)
            ctx.close()
        browser.close()
    return rows
