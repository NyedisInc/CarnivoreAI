#!/usr/bin/env python3
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
RED = (229, 51, 47, 255)
WHITE = (255, 255, 255, 255)
OUTLINE = (20, 20, 22, 255)
SUPER = 8
HEAD = [(16.5, 10.2), (11.4, 15.8), (21.6, 15.8)]
STEM = (14.4, 15.4, 18.6, 21.4)
MENU_HEAD = [(8, 1.5), (1.5, 8.5), (14.5, 8.5)]
MENU_STEM = (5.2, 8, 10.8, 14.5)


def arrow_mask(size, units, head, stem):
    scale = size * SUPER / units
    big = Image.new("L", (size * SUPER, size * SUPER), 0)
    draw = ImageDraw.Draw(big)
    draw.polygon([(x * scale, y * scale) for x, y in head], fill=255)
    draw.rectangle([stem[0] * scale, stem[1] * scale, stem[2] * scale, stem[3] * scale], fill=255)
    return big.resize((size, size), Image.LANCZOS)


def paint(base, color, mask):
    layer = Image.new("RGBA", base.size, color)
    layer.putalpha(mask)
    return Image.alpha_composite(base, layer)


def tray_icon(template_path, size):
    alpha = Image.open(template_path).convert("RGBA").getchannel("A")
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out = paint(out, RED, alpha)
    arrow = arrow_mask(size, 22, HEAD, STEM)
    ring = max(1, size // 22)
    outline = arrow.filter(ImageFilter.MaxFilter(2 * ring + 1))
    out = paint(out, OUTLINE, outline)
    return paint(out, WHITE, arrow)


def menu_icon(size):
    return paint(Image.new("RGBA", (size, size), (0, 0, 0, 0)), RED, arrow_mask(size, 16, MENU_HEAD, MENU_STEM))


def preview(path):
    small, big = Image.open(HERE / "iconUpdate.png"), Image.open(HERE / "iconUpdate@2x.png")
    menu = Image.open(HERE / "iconUpdateMenu@2x.png")
    sheet = Image.new("RGBA", (460, 280), (0, 0, 0, 255))
    for row, bg in enumerate([(28, 30, 34, 255), (236, 236, 238, 255)]):
        y0 = row * 140
        ImageDraw.Draw(sheet).rectangle([0, y0, 460, y0 + 140], fill=bg)
        sheet.alpha_composite(small, (20, y0 + 20))
        sheet.alpha_composite(big, (60, y0 + 20))
        sheet.alpha_composite(big.resize((132, 132), Image.NEAREST), (150, y0 + 4))
        sheet.alpha_composite(menu, (340, y0 + 20))
    sheet.save(path)


def main():
    template, template2 = HERE / "iconTemplate.png", HERE / "iconTemplate@2x.png"
    tray_icon(template, 22).save(HERE / "iconUpdate.png")
    tray_icon(template2, 44).save(HERE / "iconUpdate@2x.png")
    menu_icon(16).save(HERE / "iconUpdateMenu.png")
    menu_icon(32).save(HERE / "iconUpdateMenu@2x.png")
    preview(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("~/work"))


if __name__ == "__main__":
    main()
