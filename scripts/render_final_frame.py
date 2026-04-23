#!/usr/bin/env python3
"""
Render the final frame of the GoL banner animation to PNG.
The 'final frame' is the fully coalesced text after shine sweep completes
(shine_pos at SHINE_END so band is past all cells → no shine, just base colours).
"""

import argparse
import json
from pathlib import Path

from PIL import Image

# ─── Palette (identical to generate_svg.py) ──────────────────────────

PALETTE = [
    (0x00, 0xFF, 0xC8),
    (0x00, 0xC8, 0xFF),
    (0xBF, 0x00, 0xFF),
    (0xFF, 0x00, 0x9E),
]

HUE_QUANT = 48
BAND_HALF = 3
BG_COLOUR = (13, 13, 13)  # #0d0d0d


def _q(h):
    return round(h * HUE_QUANT) / HUE_QUANT


def hue_to_rgb(h):
    h = max(0.0, min(1.0, _q(h)))
    s = h * (len(PALETTE) - 1)
    lo, hi = int(s), min(int(s) + 1, len(PALETTE) - 1)
    t = s - lo
    return tuple(int(PALETTE[lo][i] + t * (PALETTE[hi][i] - PALETTE[lo][i])) for i in range(3))


def darken(rgb, factor=0.25):
    return tuple(int(c * factor) for c in rgb)


def shine_blend(rgb, t):
    return tuple(int(rgb[i] + (255 - rgb[i]) * t) for i in range(3))


def shadow_hue(grid, h, w, r, c):
    sr, sc = r - 1, c - 1
    if 0 <= sr < h and 0 <= sc < w and grid[sr][sc] is not None:
        return grid[sr][sc]
    return None


def resolve_cell(grid, h, w, r, c):
    v = grid[r][c]
    if v is not None:
        return v, True
    sh = shadow_hue(grid, h, w, r, c)
    if sh is not None:
        return sh, False
    return None, False


def cell_rgb(hue, bright, h, w, r, c, shine_pos):
    base = hue_to_rgb(hue) if bright else darken(hue_to_rgb(hue))
    dist = abs(((h - 1 - r) + c) - shine_pos)
    if dist < BAND_HALF:
        t = (1.0 - dist / BAND_HALF) * 0.85
        return shine_blend(base, t)
    return base


def compute_pair(grid, h, w, pr, c, shine_pos=-9999):
    top_r, bot_r = pr, pr + 1
    top_hue, top_bright = resolve_cell(grid, h, w, top_r, c)
    bot_hue, bot_bright = resolve_cell(grid, h, w, bot_r, c) if bot_r < h else (None, False)
    top_rgb = cell_rgb(top_hue, top_bright, h, w, top_r, c, shine_pos) if top_hue is not None else None
    bot_rgb = cell_rgb(bot_hue, bot_bright, h, w, bot_r, c, shine_pos) if bot_hue is not None else None
    return top_rgb, bot_rgb


def load_frames(path):
    with open(path) as f:
        data = json.load(f)
    gh, gw = data["grid_h"], data["grid_w"]
    grids = []
    for frame_cells in data["frames"]:
        grid = [[None] * gw for _ in range(gh)]
        for r, c, hue in frame_cells:
            grid[r][c] = hue
        grids.append(grid)
    return grids, gh, gw


def render_final_frame(frames_path: Path, output_path: Path, scale: int = 8):
    grids, gh, gw = load_frames(frames_path)
    # Play reversed: frame 0 = dissolved, frame -1 = coalesced (final)
    frames = list(reversed(grids))
    final_frame = frames[-1]

    CELL_W = 10
    CELL_H = 16
    HALF_H = CELL_H // 2
    PAD = 16

    char_rows = (gh + 1) // 2
    grid_px_w = gw * CELL_W
    grid_px_h = char_rows * CELL_H
    svg_w = grid_px_w + PAD * 2
    svg_h = grid_px_h + PAD * 2

    # shine_pos far past the grid so no shine — pure final colours
    shine_pos = float(gh + gw + 9999)

    img = Image.new("RGBA", (svg_w * scale, svg_h * scale), (0, 0, 0, 0))
    pixels = img.load()

    for pr in range(0, gh, 2):
        for c in range(gw):
            top_rgb, bot_rgb = compute_pair(final_frame, gh, gw, pr, c, shine_pos)

            char_line = pr // 2
            x_base = (PAD + c * CELL_W) * scale
            y_base = (PAD + char_line * CELL_H) * scale

            # top half
            col = top_rgb if top_rgb else None
            if col:
                for py in range(HALF_H * scale):
                    for px in range(CELL_W * scale):
                        pixels[x_base + px, y_base + py] = col + (255,)

            # bottom half
            col = bot_rgb if bot_rgb else None
            if col:
                for py in range(HALF_H * scale):
                    for px in range(CELL_W * scale):
                        pixels[x_base + px, y_base + HALF_H * scale + py] = col + (255,)

    img.save(output_path)
    print(f"Saved {output_path}  ({svg_w * scale}x{svg_h * scale} px, scale={scale}x)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="src/automatiq/data/gol_frames.json")
    parser.add_argument("--output", default="automatiq_banner_final.png")
    parser.add_argument("--scale", type=int, default=8, help="Pixel scale multiplier (default 8 = crisp upscale)")
    args = parser.parse_args()
    render_final_frame(Path(args.input), Path(args.output), scale=args.scale)
