#!/usr/bin/env python3
"""
Precompute GoL frames for the Automatiq startup animation.

Runs standard Game of Life FORWARD from the target "Automatiq" text
until the pattern dies out or stabilizes. Saves all frames to a JSON file.
The startup module plays these frames in reverse (scattered → text).

Usage:
    python precompute_gol.py [--frames 60] [--output gol_frames.json]
"""

import argparse
import json

# ─── Block font (5w × 7h) ───────────────────────────────────────────

FONT = {
    "A": [" ███ ", "█   █", "█   █", "█████", "█   █", "█   █", "█   █"],
    "u": ["     ", "     ", "█   █", "█   █", "█   █", "█   █", " ████"],
    "t": ["  █  ", "  █  ", "█████", "  █  ", "  █  ", "  █  ", "  ██ "],
    "o": ["     ", "     ", " ███ ", "█   █", "█   █", "█   █", " ███ "],
    "m": ["     ", "     ", "██ ██", "█ █ █", "█ █ █", "█   █", "█   █"],
    "a": ["     ", "     ", " ███ ", "    █", " ████", "█   █", " ████"],
    "i": ["  █  ", "     ", " ██  ", "  █  ", "  █  ", "  █  ", " ███ "],
    "Q": [" ███ ", "█   █", "█   █", "█   █", "█  ██", " ███ ", "    █"],
}

HUE_INCREMENT = 0.025


def text_to_grid(text, spacing=1):
    """Convert text to boolean pixel grid using block font."""
    ch = 7
    rows = [[] for _ in range(ch)]
    for idx, c in enumerate(text):
        g = FONT.get(c, FONT.get(c.lower(), ["     "] * ch))
        for r in range(ch):
            for p in g[r]:
                rows[r].append(p != " ")
            if idx < len(text) - 1:
                for _ in range(spacing):
                    rows[r].append(False)
    return rows, ch, len(rows[0]) if rows else 0


def count_neighbors(grid, h, w, r, c):
    count = 0
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and grid[nr][nc] is not None:
                count += 1
    return count


def step_forward(grid, h, w):
    """Standard Conway's Game of Life step. Cells carry a hue float."""
    new = [[None] * w for _ in range(h)]
    for r in range(h):
        for c in range(w):
            n = count_neighbors(grid, h, w, r, c)
            if grid[r][c] is not None:
                if n in (2, 3):
                    new[r][c] = (grid[r][c] + HUE_INCREMENT) % 1.0
            else:
                if n == 3:
                    # Inherit hue from a neighbor
                    hues = []
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            if dr == 0 and dc == 0:
                                continue
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < h and 0 <= nc < w and grid[nr][nc] is not None:
                                hues.append(grid[nr][nc])
                    new[r][c] = sum(hues) / len(hues) if hues else 0.0
    return new


def alive_count(grid, h, w):
    return sum(1 for r in range(h) for c in range(w) if grid[r][c] is not None)


def grids_equal(g1, g2, h, w):
    """Check if two grids have the same alive/dead pattern."""
    for r in range(h):
        for c in range(w):
            a1 = g1[r][c] is not None
            a2 = g2[r][c] is not None
            if a1 != a2:
                return False
    return True


def grid_to_serializable(grid, h, w):
    """Convert grid to a list of [row, col, hue] for alive cells only (compact)."""
    cells = []
    for r in range(h):
        for c in range(w):
            if grid[r][c] is not None:
                cells.append([r, c, round(grid[r][c], 4)])
    return cells


def main():
    parser = argparse.ArgumentParser(description="Precompute GoL frames for Automatiq banner")
    parser.add_argument("--frames", type=int, default=60, help="Max frames to compute")
    parser.add_argument("--output", type=str, default="gol_frames.json", help="Output JSON file")
    parser.add_argument("--text", type=str, default="AutomatiQ", help="Text to render")
    parser.add_argument("--spacing", type=int, default=1, help="Char spacing")
    parser.add_argument("--pad-top", type=int, default=2, help="Top padding rows")
    parser.add_argument("--pad-bottom", type=int, default=3, help="Bottom padding rows")
    parser.add_argument("--pad-left", type=int, default=1, help="Left padding cols")
    parser.add_argument("--pad-right", type=int, default=1, help="Right padding cols")
    args = parser.parse_args()

    # Build target grid
    rows, ch, cw = text_to_grid(args.text, spacing=args.spacing)
    gh = ch + args.pad_top + args.pad_bottom
    gw = cw + args.pad_left + args.pad_right

    target = [[None] * gw for _ in range(gh)]
    for r in range(ch):
        for c in range(cw):
            if rows[r][c]:
                # Assign hue based on horizontal position (0.0 to 0.7 spread)
                target[r + args.pad_top][c + args.pad_left] = (c / max(cw - 1, 1)) * 0.7

    target_alive = alive_count(target, gh, gw)
    print(f"Grid size: {gh}x{gw}")
    print(f"Target alive cells: {target_alive}")

    # Run GoL forward from target
    frames = [grid_to_serializable(target, gh, gw)]
    grid = [row[:] for row in target]
    prev_grid = None

    for i in range(args.frames):
        grid = step_forward(grid, gh, gw)
        ac = alive_count(grid, gh, gw)
        frames.append(grid_to_serializable(grid, gh, gw))

        print(f"  Frame {i + 1:3d}: {ac} alive cells")

        # Stop if everything died
        if ac == 0:
            print(f"All cells dead at frame {i + 1}. Stopping.")
            break

        # Stop if pattern stabilized (same as 2 frames ago = period-2 oscillator or still life)
        if prev_grid is not None and grids_equal(grid, prev_grid, gh, gw):
            print(f"Pattern stabilized at frame {i + 1}. Stopping.")
            break

        prev_grid = [row[:] for row in grid]

    print(f"\nTotal frames: {len(frames)}")
    print(f"First frame (target): {target_alive} cells")
    print(f"Last frame: {alive_count(grid, gh, gw) if frames else 0} cells")

    # Save to JSON
    # Frame 0 = target text, Frame N = most dissolved
    # The startup module will play them in REVERSE order (N → 0)
    data = {
        "text": args.text,
        "grid_h": gh,
        "grid_w": gw,
        "frame_count": len(frames),
        "frames": frames,  # Each frame is a list of [row, col, hue]
    }

    with open(args.output, "w") as f:
        json.dump(data, f)

    import os

    size_kb = os.path.getsize(args.output) / 1024
    print(f"Saved to {args.output} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
