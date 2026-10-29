
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CHEAP = {"transform", "opacity"}
EFFORT_CSS = REPO / "client" / "css" / "effort-level.css"
PAUSER = REPO / "client" / "js" / "animation-pauser.js"
PAUSE_CSS = REPO / "client" / "css" / "animation-pause.css"


def animated_properties(css: str) -> dict:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found = {}
    for match in re.finditer(r"@keyframes\s+([\w-]+)\s*\{", css):
        depth, i = 1, match.end()
        while depth:
            depth += (css[i] == "{") - (css[i] == "}")
            i += 1
        found[match.group(1)] = set(re.findall(r"([\w-]+)\s*:", css[match.end():i - 1]))
    return found


def test_keyframe_parser_can_go_red():
    sample = "@keyframes x { 0% { filter: brightness(1); opacity: 1 } 100% { mask-position: 0 0 } }"
    assert animated_properties(sample)["x"] - CHEAP == {"filter", "mask-position"}


def test_effort_keyframes_animate_only_transform_and_opacity():
    frames = animated_properties(EFFORT_CSS.read_text(encoding="utf-8"))
    assert {"effort-shimmer", "effort-sheen-window", "effort-sheen-copy", "effort-rainbow-a", "effort-rainbow-b"} <= set(frames)
    for name, props in frames.items():
        assert props <= CHEAP, f"{name} animates {sorted(props - CHEAP)}"


def test_drawer_band_and_group_label_keyframes_animate_only_transform_and_opacity():
    frames = animated_properties((REPO / "client" / "css" / "session-sidebar-colours.css").read_text(encoding="utf-8"))
    assert {"band-fx-travel", "band-fx-counter", "drawer-band-pulse"} <= set(frames)
    for name, props in frames.items():
        assert props <= CHEAP, f"{name} animates {sorted(props - CHEAP)}"


PAUSER_DRIVER = r"""
const fs = require('fs'), vm = require('vm');
let cb = null, handler = null; const observed = [];
function el(count) { const a = {}; return { nodeType: 1, count, closest: () => null, setAttribute(k) { a[k] = ''; },
  removeAttribute(k) { delete a[k]; }, has: (k) => k in a }; }
const ctx = { VisibilityObserver: function (f) { cb = f; this.observe = (t) => observed.push(t); },
  WeakSet, document: { addEventListener: (n, h, c) => { if (n === 'animationstart' && c) handler = h; } },
  getComputedStyle: (t) => ({ animationIterationCount: t.count }) };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const inf = el('infinite'), once = el('1'), inf2 = el('1, infinite');
[inf, once, inf2, inf].forEach((t) => handler({ target: t }));
cb([{ target: inf, isIntersecting: false }]);
const hidden = inf.has('data-anim-offscreen');
cb([{ target: inf, isIntersecting: true }]);
console.log(JSON.stringify({ observed: observed.length, infinite: observed.includes(inf),
  once: observed.includes(once), list: observed.includes(inf2), hidden, shown: !inf.has('data-anim-offscreen') }));
"""


def test_pauser_marks_an_offscreen_infinite_animation_and_unmarks_it():
    node = shutil.which("node")
    assert node, "node is required to run the pauser (a missing tool must fail, not pass)"
    out = subprocess.run([node, "-e", PAUSER_DRIVER, str(PAUSER)], capture_output=True, text=True, check=True)
    got = json.loads(out.stdout)
    assert got == {"observed": 2, "infinite": True, "once": False, "list": True, "hidden": True, "shown": True}


def test_pause_stylesheet_pauses_never_cancels():
    css = re.sub(r"/\*.*?\*/", "", PAUSE_CSS.read_text(encoding="utf-8"), flags=re.S)
    assert re.search(r"\[data-anim-offscreen\][^{]*\{[^}]*animation-play-state:\s*paused\s*!important", css)
    css = re.sub(r':root\[data-motion="off"\][^{]*\{[^}]*\}', "", css)
    assert "animation:" not in css and "animation-name" not in css
    for cover in (".oc-tabpane-hidden", "[data-parked-terminals]", "body.menu-page-open"):
        assert cover in css
