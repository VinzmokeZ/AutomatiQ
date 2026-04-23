#!/usr/bin/env python3
"""
Generate an animated SVG that faithfully recreates the Automatiq terminal banner.

Matches the half-block (▀/▄) rendering, shadow logic, and per-cell shine sweep
from automatiq_banner.py exactly.

Usage:
    python generate_svg.py [--input src/automatiq/data/gol_frames.json] [--output automatiq_banner.svg]
"""

import argparse
import json
from pathlib import Path

# ─── Palette (identical to automatiq_banner.py) ─────────────────────

PALETTE = [
    (0x00, 0xFF, 0xC8),
    (0x00, 0xC8, 0xFF),
    (0xBF, 0x00, 0xFF),
    (0xFF, 0x00, 0x9E),
]

HUE_QUANT = 48


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


def hex_rgb(rgb):
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


BG = "#0d0d0d"

# ─── Frame loading ───────────────────────────────────────────────────


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


# ─── Cell computation (matches _render_cell_region exactly) ──────────

BAND_HALF = 3


def shadow_hue(grid, h, w, r, c):
    sr, sc = r - 1, c - 1
    if 0 <= sr < h and 0 <= sc < w and grid[sr][sc] is not None:
        return grid[sr][sc]
    return None


def resolve_cell(grid, h, w, r, c):
    """Returns (hue, bright) or (None, False) — matching the terminal renderer."""
    v = grid[r][c]
    if v is not None:
        return v, True
    sh = shadow_hue(grid, h, w, r, c)
    if sh is not None:
        return sh, False
    return None, False


def cell_rgb(hue, bright, h, w, r, c, shine_pos):
    """Compute the final RGB for a resolved cell with shine applied."""
    base = hue_to_rgb(hue) if bright else darken(hue_to_rgb(hue))
    dist = abs(((h - 1 - r) + c) - shine_pos)
    if dist < BAND_HALF:
        t = (1.0 - dist / BAND_HALF) * 0.85
        return shine_blend(base, t)
    return base


# ─── Half-block pair computation ─────────────────────────────────────


def compute_pair(grid, h, w, pr, c, shine_pos=-999):
    """
    For a column c at row-pair (pr, pr+1), compute what the terminal
    renderer would produce for a single character cell:

    Returns (top_rgb_or_None, bot_rgb_or_None).
    None means that half is the background colour.
    """
    top_r, bot_r = pr, pr + 1
    top_hue, top_bright = resolve_cell(grid, h, w, top_r, c)
    bot_hue, bot_bright = resolve_cell(grid, h, w, bot_r, c) if bot_r < h else (None, False)

    top_rgb = cell_rgb(top_hue, top_bright, h, w, top_r, c, shine_pos) if top_hue is not None else None
    bot_rgb = cell_rgb(bot_hue, bot_bright, h, w, bot_r, c, shine_pos) if bot_hue is not None else None
    return top_rgb, bot_rgb


# ─── SVG generation ──────────────────────────────────────────────────


def generate_svg(frames_path: Path, output_path: Path):
    grids, gh, gw = load_frames(frames_path)
    frames = list(reversed(grids))  # dissolved → coalesced
    num_frames = len(frames)
    final_frame = frames[-1]

    CELL_W = 10
    CELL_H = 16  # half-block packs 2 grid rows into 1 character
    HALF_H = CELL_H // 2
    PAD = 16
    FRAME_DUR = 0.05
    SHINE_STEPS = 50
    SHINE_DELAY = 0.0325
    HOLD_DUR = 1.0

    coalesce_dur = num_frames * FRAME_DUR
    shine_dur = SHINE_STEPS * SHINE_DELAY
    total_dur = coalesce_dur + shine_dur + HOLD_DUR

    char_rows = (gh + 1) // 2
    grid_px_w = gw * CELL_W
    grid_px_h = char_rows * CELL_H
    svg_w = grid_px_w + PAD * 2
    svg_h = grid_px_h + PAD * 2

    # Shine sweep range
    SHINE_START = float(-gw)
    SHINE_END = float(gh + gw)

    # ── Build per-half-cell keyframes ─────────────────────────────────
    # Each position (pr, c) produces two half-cell rects: top and bottom.
    # We build a keyframe sequence for each half-cell.
    # Key: ("t"|"b", pr, c) → list of (time_sec, hex_color_or_None)
    # None means transparent (background).

    half_cells = {}  # key → [(t_sec, hex_or_None), ...]

    for pr in range(0, gh, 2):
        for c in range(gw):
            top_seq = []
            bot_seq = []

            # Phase 1: coalesce frames (no shine)
            for fi, frame in enumerate(frames):
                t_sec = fi * FRAME_DUR
                top_rgb, bot_rgb = compute_pair(frame, gh, gw, pr, c)
                top_seq.append((t_sec, hex_rgb(top_rgb) if top_rgb else None))
                bot_seq.append((t_sec, hex_rgb(bot_rgb) if bot_rgb else None))

            # Phase 2: shine sweep on final frame
            for si in range(SHINE_STEPS + 1):
                t_sec = coalesce_dur + si * SHINE_DELAY
                shine_pos = SHINE_START + (si / SHINE_STEPS) * (SHINE_END - SHINE_START)
                top_rgb, bot_rgb = compute_pair(final_frame, gh, gw, pr, c, shine_pos)
                top_seq.append((t_sec, hex_rgb(top_rgb) if top_rgb else None))
                bot_seq.append((t_sec, hex_rgb(bot_rgb) if bot_rgb else None))

            # Only include if this half-cell is ever visible
            if any(s[1] is not None for s in top_seq):
                half_cells[("t", pr, c)] = top_seq
            if any(s[1] is not None for s in bot_seq):
                half_cells[("b", pr, c)] = bot_seq

    # ── Compress: drop consecutive duplicates ────────────────────────

    def compress(seq):
        out = [seq[0]]
        for s in seq[1:]:
            if s[1] != out[-1][1]:
                out.append(s)
        # Ensure a terminal keyframe
        out.append((total_dur - 0.001, seq[-1][1]))
        return tuple((round(s[0] / total_dur * 100, 3), s[1]) for s in out)

    # ── Deduplicate → CSS classes ────────────────────────────────────

    seq_to_cls = {}
    hc_cls = {}

    for key, seq in half_cells.items():
        ckey = compress(seq)
        if ckey not in seq_to_cls:
            seq_to_cls[ckey] = f"c{len(seq_to_cls)}"
        hc_cls[key] = seq_to_cls[ckey]

    # Build CSS @keyframes
    css_blocks = []
    for ckey, cls in seq_to_cls.items():
        lines = [f"  @keyframes {cls} {{"]
        for pct, col in ckey:
            fill = col if col else BG
            op = "1" if col else "0"
            lines.append(f"    {pct}%{{fill:{fill};opacity:{op}}}")
        last_col = ckey[-1][1]
        if ckey[-1][0] < 100.0:
            fill = last_col if last_col else BG
            op = "1" if last_col else "0"
            lines.append(f"    100%{{fill:{fill};opacity:{op}}}")
        lines.append("  }")
        css_blocks.append("\n".join(lines))

    # ── Assemble SVG ─────────────────────────────────────────────────

    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}">')

    # CSS
    out.append("<style>")
    out.append(
        f"  .hc{{animation-duration:{total_dur:.3f}s;"
        f"animation-timing-function:steps(1,end);"
        f"animation-iteration-count:infinite}}"
    )
    for block in css_blocks:
        out.append(block)
    out.append("</style>")

    # Half-cell rects
    # Row pr renders at y = PAD + (pr // 2) * CELL_H
    # Top half: y offset + 0, height HALF_H
    # Bot half: y offset + HALF_H, height HALF_H
    out.append("<g>")
    for (half, pr, c), cls in sorted(hc_cls.items()):
        x = PAD + c * CELL_W
        char_line = pr // 2
        y_base = PAD + char_line * CELL_H
        y = y_base if half == "t" else y_base + HALF_H

        # Initial state from first keyframe
        seq = half_cells[(half, pr, c)]
        init_col = seq[0][1]
        init_fill = init_col if init_col else BG
        init_op = "1" if init_col else "0"

        out.append(
            f'<rect x="{x}" y="{y}" width="{CELL_W}" height="{HALF_H}" '
            f'fill="{init_fill}" opacity="{init_op}" '
            f'class="hc" style="animation-name:{cls}"/>'
        )
    out.append("</g>")
    out.append("</svg>")

    output_path.write_text("\n".join(out), encoding="utf-8")
    size_kb = output_path.stat().st_size / 1024
    print(f"Saved {output_path}  ({size_kb:.1f} KB, {len(seq_to_cls)} unique sequences, {len(hc_cls)} half-cells)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate animated SVG banner")
    parser.add_argument("--input", default="src/automatiq/data/gol_frames.json")
    parser.add_argument("--output", default="automatiq_banner.svg")
    args = parser.parse_args()
    generate_svg(Path(args.input), Path(args.output))
