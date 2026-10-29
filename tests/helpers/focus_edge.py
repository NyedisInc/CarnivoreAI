
from __future__ import annotations

_READ_JS = """(sel) => {
    const el = document.querySelector(sel);
    const cv = document.createElement('canvas');
    cv.width = cv.height = 1;
    const cx = cv.getContext('2d', {willReadFrequently: true});
    const lum = (c, under) => {
        cx.clearRect(0, 0, 1, 1);
        for (const paint of [under, c]) {
            if (!paint) continue;
            cx.fillStyle = paint;
            cx.fillRect(0, 0, 1, 1);
        }
        const m = Array.from(cx.getImageData(0, 0, 1, 1).data);
        const [r, g, b] = m.slice(0, 3).map((v) => {
            v /= 255;
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const cs = getComputedStyle(el);
    const box = el.getBoundingClientRect();
    const ground = getComputedStyle(el).getPropertyValue('--oc-ground-page').trim() || 'black';
    const [hi, lo] = [lum(cs.borderTopColor, ground), lum(ground)].sort((m, n) => n - m);
    return {edge: cs.borderTopColor, edgeWidth: cs.borderTopWidth, shadow: cs.boxShadow,
            outlineStyle: cs.outlineStyle, outlineWidth: cs.outlineWidth,
            outlineColour: cs.outlineColor, w: box.width, h: box.height,
            contrast: (hi + 0.05) / (lo + 0.05)};
}"""


def settle_transitions(page, selector: str, timeout_ms: int) -> None:
    page.evaluate("() => new Promise((r) => requestAnimationFrame(r))")
    page.wait_for_function(
        "(sel) => document.querySelector(sel).getAnimations().length === 0",
        arg=selector, timeout=timeout_ms,
    )


def measure_focus_edge(page, selector: str, focus: str | None = None, how: str = "key",
                       settle_ms: int = 300) -> dict:
    focus = focus or selector
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    settle_transitions(page, selector, timeout_ms=max(settle_ms * 10, 3000))
    rest = page.evaluate(_READ_JS, selector)
    if how == "click":
        page.click(focus, timeout=5000)
    else:
        page.keyboard.press("Shift")
        page.evaluate("sel => document.querySelector(sel).focus()", focus)
    settle_transitions(page, selector, timeout_ms=max(settle_ms * 10, 3000))
    after = page.evaluate(_READ_JS, selector)
    focused = page.evaluate("sel => document.activeElement === document.querySelector(sel)", focus)
    return {"rest": rest, "focus": after, "focused": focused}


def focus_edge_failures(m: dict) -> list[str]:
    rest, focus = m["rest"], m["focus"]
    checks = [
        (m["focused"], "focus did not land"),
        (focus["outlineStyle"] == "none", f"outline {focus['outlineStyle']} {focus['outlineWidth']} {focus['outlineColour']}"),
        (focus["edge"] != rest["edge"], f"edge colour unchanged {rest['edge']}"),
        (focus["contrast"] > rest["contrast"], f"edge contrast {rest['contrast']:.2f} -> {focus['contrast']:.2f}"),
        (focus["edgeWidth"] == rest["edgeWidth"], f"edge width {rest['edgeWidth']} -> {focus['edgeWidth']}"),
        (focus["shadow"] == rest["shadow"], f"a shadow was added, adding thickness: {rest['shadow']} -> {focus['shadow']}"),
        ((focus["w"], focus["h"]) == (rest["w"], rest["h"]), f"box moved {rest['w']}x{rest['h']} -> {focus['w']}x{focus['h']}"),
    ]
    return [why for ok, why in checks if not ok]


def assert_focus_edge(m: dict, label: str = "") -> None:
    failures = focus_edge_failures(m)
    assert not failures, (label, failures, m)
