#!/bin/bash

set -euo pipefail

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/macOS/assets/AppIcon-1024.png"
OUT_DIR="$REPO_ROOT/client/assets/icons"
PYTHON_BIN="$REPO_ROOT/venv/bin/python3"

if [ ! -f "$SRC" ]; then
    echo "generate-web-icons: source not found: $SRC" >&2
    exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

if ! command -v sips >/dev/null 2>&1; then
    echo "generate-web-icons: sips not found (macOS only)" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

for size in 192 512; do
    sips -s format png -z "$size" "$size" "$SRC" \
        --out "$OUT_DIR/icon-${size}.png" >/dev/null
    echo "generate-web-icons: wrote icon-${size}.png"
done

sips -s format png -z 64 64 "$SRC" --out "$OUT_DIR/header-icon.png" >/dev/null
echo "generate-web-icons: wrote header-icon.png"
sips -s format png -z 128 128 "$SRC" --out "$OUT_DIR/header-icon@2x.png" >/dev/null
echo "generate-web-icons: wrote header-icon@2x.png"

"$PYTHON_BIN" - "$SRC" "$OUT_DIR" <<'PYEOF'
import sys
from PIL import Image

src_path, out_dir = sys.argv[1], sys.argv[2]

# Matches client/manifest.webmanifest background_color / theme_color, the
# app's default (Claude theme) page background.
BG = (0x0a, 0x0a, 0x0a, 0xff)

# Android's safe zone for maskable icons is a centered circle at ~66% of the
# canvas. Scaling the source content to 60% of canvas width leaves margin so
# every OEM mask shape (circle, squircle, rounded square) keeps the full
# mark.
MASKABLE_SAFE_FRACTION = 0.60

src = Image.open(src_path).convert("RGBA")


def flatten(im: Image.Image, size: int) -> Image.Image:
    """Resize im to size x size and composite it onto an opaque BG canvas."""
    resized = im.resize((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), BG)
    canvas.alpha_composite(resized)
    return canvas.convert("RGB")


# apple-touch-icon: same edge-to-edge scale as the transparent variants, just
# flattened so iOS never has to guess at a transparent pixel.
apple = flatten(src, 180)
apple.save(f"{out_dir}/icon-180.png")
print("generate-web-icons: wrote icon-180.png (flattened)")

# Maskable 512: crop to the visible mark, scale it into the safe zone, paste
# centered on an opaque BG canvas.
bbox = src.getbbox()
cropped = src.crop(bbox)
cw, ch = cropped.size
canvas_size = 512
target = int(canvas_size * MASKABLE_SAFE_FRACTION)
scale = target / max(cw, ch)
new_w, new_h = max(1, round(cw * scale)), max(1, round(ch * scale))
mark = cropped.resize((new_w, new_h), Image.LANCZOS)

canvas = Image.new("RGBA", (canvas_size, canvas_size), BG)
paste_x = (canvas_size - new_w) // 2
paste_y = (canvas_size - new_h) // 2
canvas.alpha_composite(mark, (paste_x, paste_y))
canvas.convert("RGB").save(f"{out_dir}/icon-512-maskable.png")
print("generate-web-icons: wrote icon-512-maskable.png (safe-zone, flattened)")
PYEOF

echo "generate-web-icons: done ($OUT_DIR)"
