#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image

WINDOW_W = 600
WINDOW_H = 561
TITLEBAR_H = 28
STATUS_PATH_BARS_H = 59

SOURCE_W = 1024
SOURCE_H = 957
SOURCE_CROSSHAIR_LEFT = (243, 662)
SOURCE_CROSSHAIR_RIGHT = (779, 662)
SOURCE_FRAME_TOP = 535
SOURCE_FRAME_BOTTOM = 790

SOURCE_TO_WINDOW_SCALE = WINDOW_W / SOURCE_W


def _scale_point(point: tuple[int, int]) -> tuple[float, float]:
    x, y = point
    return (x * SOURCE_TO_WINDOW_SCALE, y * SOURCE_TO_WINDOW_SCALE)


APP_ICON_X = round(_scale_point(SOURCE_CROSSHAIR_LEFT)[0])
LINK_ICON_X = round(_scale_point(SOURCE_CROSSHAIR_RIGHT)[0])
ICON_Y = round(_scale_point(SOURCE_CROSSHAIR_LEFT)[1])

FRAME_TOP = _scale_point((0, SOURCE_FRAME_TOP))[1]
FRAME_BOTTOM = _scale_point((0, SOURCE_FRAME_BOTTOM))[1]


class ArtworkError(RuntimeError):
    pass


def default_source(repo_root: Path) -> Path:
    return repo_root / "macOS" / "assets" / "dmg" / "background-source.png"


def default_out_dir(repo_root: Path) -> Path:
    return repo_root / "macOS" / "assets" / "dmg"


def find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / ".git").exists():
            return parent
    return start


def render_pngs(source: Path, out_dir: Path) -> tuple[Path, Path]:
    try:
        image = Image.open(source).convert("RGB")
    except (OSError, ValueError) as exc:
        raise ArtworkError(f"could not open source image {source}: {exc}") from exc

    png_1x = out_dir / "background.png"
    png_2x = out_dir / "background@2x.png"
    image.resize((WINDOW_W, WINDOW_H), Image.LANCZOS).save(png_1x)
    image.resize((WINDOW_W * 2, WINDOW_H * 2), Image.LANCZOS).save(png_2x)
    return png_1x, png_2x


def fuse_tiff(png_1x: Path, png_2x: Path, tiff_path: Path) -> None:
    cmd = [
        "tiffutil", "-cathidpicheck",
        str(png_1x), str(png_2x),
        "-out", str(tiff_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except FileNotFoundError as exc:
        raise ArtworkError("tiffutil not found; it ships with macOS") from exc
    except subprocess.CalledProcessError as exc:
        raise ArtworkError(
            f"tiffutil failed ({exc.returncode}): "
            f"{exc.stderr.decode(errors='replace')}"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    repo_root = find_repo_root(here)

    parser = argparse.ArgumentParser(
        description="render the carnivore dmg background from the owner's source art"
    )
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    source: Path = args.source or default_source(repo_root)
    out_dir: Path = args.out_dir or default_out_dir(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    tiff_path = out_dir / "background.tiff"
    try:
        png_1x, png_2x = render_pngs(source, out_dir)
        fuse_tiff(png_1x, png_2x, tiff_path)
    except ArtworkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"wrote background.png ({WINDOW_W}x{WINDOW_H}), "
        f"background@2x.png ({WINDOW_W * 2}x{WINDOW_H * 2}) and "
        f"background.tiff in {out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
