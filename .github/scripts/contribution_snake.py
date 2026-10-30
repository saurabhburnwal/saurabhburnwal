#!/usr/bin/env python3
"""Draw the contribution-graph snake for the profile README.

Reads the public contribution calendar (the same squares visitors see on the
profile) and writes a light and a dark animated SVG. The snake only ever moves
over real day squares, and the month, weekday and Less/More labels are placed
the way GitHub places them.
"""

import argparse
import html
import os
import re
import sys
import urllib.request
from collections import deque

CELL = 10
GAP = 3
PITCH = CELL + GAP
STEP_MS = 100

# Offsets measured from the calendar on github.com, relative to the grid.
DAY_LABEL_X = -31
LABEL_BASELINE = 13.5  # baseline inside GitHub's 18px label line box
MONTH_LINE_TOP = -19
LEGEND_TOP = 11  # gap between the grid and the legend squares
LEGEND_STEP = 14
LEGEND_RIGHT = 58.4  # from the grid's right edge to the last legend square

PAD_LEFT = 1
PAD_TOP = 1
PAD_RIGHT = 18  # room for a month label that starts on the last column

# Snake segments, head first: (size, corner radius)
SEGMENTS = [(11.7, 3.7), (10.0, 3.3), (8.8, 2.9), (8.0, 2.7)]

FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif'

THEMES = {
    "github-snake.svg": {
        "levels": ["#eff2f5", "#aceebb", "#4ac26b", "#2da44e", "#116329"],
        "border": "#1f23280d",
        "text": "#1f2328",
        "muted": "#59636e",
        "snake": "purple",
    },
    "github-snake-dark.svg": {
        "levels": ["#151b23", "#033a16", "#196c2e", "#2ea043", "#56d364"],
        "border": "#0104090d",
        "text": "#f0f6fc",
        "muted": "#9198a1",
        "snake": "purple",
    },
}


def fetch_calendar(user):
    url = f"https://github.com/users/{user}/contributions"
    req = urllib.request.Request(url, headers={"User-Agent": "contribution-snake"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8")


def attr(tag, name):
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def parse_calendar(page):
    """Return ({(col, row): level}, [(col, label)])."""
    cells = {}
    for tag in re.findall(r"<td\b[^>]*\bdata-date=[^>]*>", page):
        pos = re.search(r"contribution-day-component-(\d+)-(\d+)", attr(tag, "id") or "")
        if pos:
            row, col = int(pos.group(1)), int(pos.group(2))
            cells[(col, row)] = int(attr(tag, "data-level") or 0)
    if not cells:
        sys.exit("No contribution squares found in the calendar page")

    # GitHub gives each month label a colspan and lays them out left to right
    months, col = [], 0
    for tag, body in re.findall(r"(<td\b[^>]*ContributionCalendar-label[^>]*>)(.*?)</td>", page, re.S):
        span = attr(tag, "colspan")
        if span is None:
            continue
        text = re.search(r'aria-hidden="true"[^>]*>\s*([^<]*?)\s*<', body)
        if text and text.group(1):
            months.append((col, html.unescape(text.group(1))))
        col += int(span)
    return cells, months


def neighbours(cell, cells):
    c, r = cell
    for nxt in ((c, r - 1), (c + 1, r), (c, r + 1), (c - 1, r)):
        if nxt in cells:
            yield nxt


def find_path(cells, body, goal, avoid=frozenset(), respect_body=True):
    """Shortest path for the head to a cell matching goal(cell), or None.

    A body segment k (1 = neck) is still in place for the first len - 1 - k
    moves, so its cell can only be entered after that.
    """
    free_at = {seg: len(body) - k for k, seg in enumerate(body) if k > 0} if respect_body else {}
    start = body[0]
    prev = {start: None}
    queue = deque([(start, 0)])
    while queue:
        cur, dist = queue.popleft()
        if cur != start and goal(cur):
            path = []
            while cur != start:
                path.append(cur)
                cur = prev[cur]
            return path[::-1]
        for nxt in neighbours(cur, cells):
            if nxt in prev or nxt in avoid or dist + 1 < free_at.get(nxt, 0):
                continue
            prev[nxt] = cur
            queue.append((nxt, dist + 1))
    return None


def plan_moves(cells):
    """Head positions, one per step; the snake ends in the pose it starts in."""
    cols = max(c for c, _ in cells) + 1
    row0 = next((r for r in range(7) if all((c, r) in cells for c in range(4))), None)
    if cols < 4 or row0 is None:
        sys.exit("Calendar is too small for the snake")
    home = [(c, row0) for c in range(4)]
    body = list(home)
    moves = []

    def advance(path):
        for cell in path:
            body.insert(0, cell)
            body.pop()
            moves.append(cell)

    left = {cell for cell, level in cells.items() if level > 0}
    while left:
        def is_food(cell):
            return cell in left

        path = find_path(cells, body, is_food) or find_path(cells, body, is_food, respect_body=False)
        if path is None:
            break
        advance(path)
        left.difference_update(path)

    # Come back to the starting pose so the loop is seamless: reach the cell
    # behind the tail's home without crossing home, then slide into place.
    # A dead end (the lone Sunday square of a new week) forces the snake to
    # turn back over itself, so fall back to ignoring the body.
    def route(goal, avoid=frozenset()):
        path = find_path(cells, body, goal, avoid) or find_path(cells, body, goal, avoid, respect_body=False)
        if path is None:
            sys.exit("The snake cannot get back to its starting pose")
        return path

    lane = frozenset(home[:3])
    if body[0] in lane:
        advance(route(lambda cell: cell not in lane and cell != home[3]))
    advance(route(lambda cell: cell == home[3], avoid=lane))
    advance(home[2::-1])
    return home, moves


def check_moves(cells, home, moves):
    body = list(home)
    for i, cell in enumerate(moves):
        prev = body[0]
        if cell not in cells:
            sys.exit(f"Step {i} leaves the grid at {cell}")
        if abs(cell[0] - prev[0]) + abs(cell[1] - prev[1]) != 1:
            sys.exit(f"Step {i} is not a single move: {prev} -> {cell}")
        body.insert(0, cell)
        body.pop()
        if len(set(body)) != len(body):
            print(f"warning: the snake overlaps itself at step {i}", file=sys.stderr)
    if body != home:
        sys.exit("The snake does not end where it starts")


def pct(step, total):
    return f"{step * 100 / total:.4f}".rstrip("0").rstrip(".") + "%"


def render(cells, months, home, moves, theme):
    cols = max(c for c, _ in cells) + 1
    grid_w = cols * PITCH - GAP
    grid_h = 7 * PITCH - GAP
    gx = PAD_LEFT - DAY_LABEL_X
    gy = PAD_TOP - MONTH_LINE_TOP
    width = gx + grid_w + PAD_RIGHT
    height = gy + grid_h + LEGEND_TOP + CELL + 4 + PAD_TOP
    total = len(moves)
    duration = total * STEP_MS

    def centre(cell):
        return gx + cell[0] * PITCH + CELL / 2, gy + cell[1] * PITCH + CELL / 2

    # Q holds every position the snake occupies, tail of the start pose first,
    # so segment i sits at Q[3 + step - i].
    queue = home[::-1] + moves
    eaten = {}
    for step, cell in enumerate(moves, 1):
        eaten.setdefault(cell, step)

    css = [
        f".l{{font:12px {FONT};fill:{theme['text']}}}",
        f".m{{fill:{theme['muted']}}}",
        f".c{{stroke:{theme['border']};stroke-width:1px;animation:none {duration}ms linear infinite}}",
        f".s{{fill:{theme['snake']};animation:none {duration}ms linear infinite}}",
    ]
    out = []

    for col, label in months:
        out.append(f'<text class="l" x="{gx + col * PITCH}" y="{gy + MONTH_LINE_TOP + LABEL_BASELINE}">{html.escape(label)}</text>')
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        y = gy + row * PITCH - 5 + LABEL_BASELINE
        out.append(f'<text class="l" x="{gx + DAY_LABEL_X}" y="{y}">{label}</text>')

    for n, (cell, level) in enumerate(sorted(cells.items())):
        x, y = gx + cell[0] * PITCH + 0.5, gy + cell[1] * PITCH + 0.5
        rect = f'x="{x}" y="{y}" width="{CELL - 1}" height="{CELL - 1}" rx="1.5"'
        if level and cell in eaten:
            at = eaten[cell]
            css.append(
                f"@keyframes e{n}{{0%,{pct(at, total)}{{fill:{theme['levels'][level]}}}"
                f"{pct(at + 0.01, total)},100%{{fill:{theme['levels'][0]}}}}}"
            )
            out.append(f'<rect class="c" style="animation-name:e{n}" {rect}/>')
        else:
            out.append(f'<rect class="c" fill="{theme["levels"][level]}" {rect}/>')

    for i, (size, radius) in enumerate(SEGMENTS):
        frames = []
        for step in range(total + 1):
            here = queue[3 + step - i]
            if 0 < step < total:
                before, after = queue[2 + step - i], queue[4 + step - i]
                if (here[0] - before[0], here[1] - before[1]) == (after[0] - here[0], after[1] - here[1]):
                    continue
            x, y = centre(here)
            frames.append(f"{pct(step, total)}{{transform:translate({x}px,{y}px)}}")
        css.append(f"@keyframes s{i}{{{''.join(frames)}}}")
        x, y = centre(queue[3 - i])
        out.append(
            f'<rect class="s" style="animation-name:s{i};transform:translate({x}px,{y}px)" '
            f'x="{-size / 2}" y="{-size / 2}" width="{size}" height="{size}" rx="{radius}"/>'
        )

    legend_y = gy + grid_h + LEGEND_TOP
    first = gx + grid_w - LEGEND_RIGHT - 4 * LEGEND_STEP - CELL
    text_y = legend_y - 4 + LABEL_BASELINE
    out.append(f'<text class="l m" x="{first - 4}" y="{text_y}" text-anchor="end">Less</text>')
    for level, colour in enumerate(theme["levels"]):
        x = first + level * LEGEND_STEP + 0.5
        out.append(f'<rect class="c" fill="{colour}" x="{x}" y="{legend_y + 0.5}" width="{CELL - 1}" height="{CELL - 1}" rx="1.5"/>')
    out.append(f'<text class="l m" x="{first + 4 * LEGEND_STEP + CELL + 4}" y="{text_y}">More</text>')

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        f"<style>{''.join(css)}</style>" + "".join(out) + "</svg>\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user", required=True)
    parser.add_argument("--out", default="dist")
    parser.add_argument("--html", help="read the calendar from a saved page instead of github.com")
    args = parser.parse_args()

    if args.html:
        with open(args.html, encoding="utf-8") as f:
            page = f.read()
    else:
        page = fetch_calendar(args.user)
    cells, months = parse_calendar(page)
    home, moves = plan_moves(cells)
    check_moves(cells, home, moves)

    os.makedirs(args.out, exist_ok=True)
    for name, theme in THEMES.items():
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as f:
            f.write(render(cells, months, home, moves, theme))
    eaten = sum(1 for level in cells.values() if level)
    print(f"{len(cells)} days, {eaten} active, {len(moves)} steps")


if __name__ == "__main__":
    main()
