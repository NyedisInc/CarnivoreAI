#!/usr/bin/env python3

from __future__ import annotations

import re

def parse_color(text: str) -> tuple[float, float, float, float]:
    s = text.strip()
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) not in (6, 8):
            raise ValueError(f"not a hex colour: {text!r}")
        r, g, b = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        a = int(h[6:8], 16) / 255.0 if len(h) == 8 else 1.0
        return float(r), float(g), float(b), a
    nums = re.findall(r"[-+]?\d*\.?\d+", s)
    if len(nums) < 3:
        raise ValueError(f"not a colour: {text!r}")
    r, g, b = (float(nums[0]), float(nums[1]), float(nums[2]))
    a = float(nums[3]) if len(nums) > 3 else 1.0
    return r, g, b, a


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    def chan(c: float) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def over(top: tuple[float, float, float, float],
         bottom: tuple[float, float, float]) -> tuple[float, float, float]:
    a = top[3]
    return tuple(top[i] * a + bottom[i] * (1 - a) for i in range(3))


def decode_1x1_png(data: bytes) -> tuple[int, int, int, int]:
    import struct
    import zlib
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, depth, ctype, width = 8, b"", None, None, None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, _h, depth, ctype = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + length
    if depth != 8 or ctype not in (2, 6) or width != 1:
        raise ValueError(f"unsupported PNG: depth={depth} ctype={ctype} width={width}")
    raw = zlib.decompress(idat)
    px = raw[1:]
    if ctype == 2:
        return px[0], px[1], px[2], 255
    return px[0], px[1], px[2], px[3]


def sample_pixel(page, x: float, y: float,
                 freeze_animations: bool = False) -> tuple[int, int, int, int]:
    clip = {"x": x, "y": y, "width": 1, "height": 1}
    if freeze_animations:
        shot = page.screenshot(clip=clip, animations="disabled")
    else:
        shot = page.screenshot(clip=clip)
    return decode_1x1_png(shot)


def measure_show_through(page, selector: str, page_bg: str, inset_x: float = 10.0,
                         inset_y: float = 4.0) -> dict:
    rect = page.evaluate(
        "s => { const e = document.querySelector(s); if (!e) return null;"
        "const r = e.getBoundingClientRect();"
        "return {x: r.left, y: r.top, w: r.width, h: r.height}; }", selector)
    if not rect:
        raise RuntimeError(f"no element for {selector!r}, so nothing could be sampled")
    x = rect["x"] + inset_x
    y = rect["y"] + rect["h"] - inset_y
    prev = page.evaluate("() => document.documentElement.style.background")
    page.evaluate("() => { document.documentElement.style.background = '#000000'; }")
    black = sample_pixel(page, x, y)[:3]
    page.evaluate("() => { document.documentElement.style.background = '#ffffff'; }")
    white = sample_pixel(page, x, y)[:3]
    page.evaluate("c => { document.documentElement.style.background = c; }", page_bg)
    themed = sample_pixel(page, x, y)[:3]
    page.evaluate("p => { document.documentElement.style.background = p; }", prev)
    show = sum((white[i] - black[i]) for i in range(3)) / (3 * 255.0)
    return {
        "over_black": black,
        "over_white": white,
        "over_theme": themed,
        "show_through": show,
        "fill_fraction": 1.0 - show,
        "sample_point": (x, y),
    }
