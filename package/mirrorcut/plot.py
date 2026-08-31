# -*- coding: utf-8 -*-
"""Evidence-path plots, stdlib only: an SVG of every switch's e-process over rows.

    from mirrorcut.plot import evidence_svg
    evidence_svg(screen, "screen.svg")            # from a live screen
    mirrorcut report screen.jsonl --svg out.svg   # from a ledger, via the CLI
"""
from __future__ import annotations

import math
from pathlib import Path

__all__ = ["evidence_svg"]

_COLORS = ["#c94f3d", "#d98e3a", "#5e8f6a", "#6f7f9d", "#8a8f8a",
           "#a7693f", "#7a5f8f", "#4f8f8a", "#b3567a", "#6b6f4a"]


def evidence_svg(screen, out_path, width=880, height=420, animate=False):
    """Write the admission-evidence paths of a screen to an SVG file."""
    W, H = width, height
    PAD_L, PAD_R, PAD_T, PAD_B = 64, 150, 46, 40
    lo, hi = math.log(0.04), math.log(1.4 * screen.threshold)
    n_max = max((e.path[-1][0] for e in screen.ev if e.path), default=1)

    def x(row):
        return PAD_L + (W - PAD_L - PAD_R) * row / n_max

    def y(ev):
        v = max(min(ev, 1.4 * screen.threshold), 0.04)
        return PAD_T + (H - PAD_T - PAD_B) * (1 - (math.log(v) - lo) / (hi - lo))

    parts = ['<rect width="%d" height="%d" fill="#111312" rx="10"/>' % (W, H)]
    ty = y(screen.threshold)
    parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#b8b4ac" '
                 'stroke-dasharray="5,4" stroke-width="1.2"/>'
                 % (PAD_L, ty, W - PAD_R, ty))
    parts.append('<text x="%d" y="%.1f" fill="#b8b4ac" font-size="11" '
                 'font-family="Georgia,serif">admit at k/&#945; = %.0f</text>'
                 % (PAD_L + 4, ty - 6, screen.threshold))
    oy = y(1.0)
    parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#2a2d2b"/>'
                 % (PAD_L, oy, W - PAD_R, oy))
    ends = []
    for idx, (name, e) in enumerate(zip(screen.names, screen.ev)):
        if not e.path:
            continue
        pts = [(x(0), y(1.0))] + [(x(r), y(up)) for r, up, dn, t in e.path]
        col = _COLORS[idx % len(_COLORS)]
        d = "M " + " L ".join("%.1f %.1f" % p for p in pts)
        parts.append('<path d="%s" fill="none" stroke="%s" stroke-width="2.2"/>'
                     % (d, col))
        ends.append((pts[-1][1], name, e.state, col, pts[-1][0]))
    prev = -100.0
    for ly, name, state, col, lx in sorted(ends):
        ly = max(ly, prev + 15.0)
        prev = ly
        parts.append('<text x="%.1f" y="%.1f" fill="%s" font-size="12.5" '
                     'font-family="Georgia,serif" font-weight="%s">%s &#8594; %s</text>'
                     % (min(lx + 8, W - PAD_R + 6), ly + 4, col,
                        "700" if state == "admitted" else "400", name, state))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
           'viewBox="0 0 %d %d">%s</svg>' % (W, H, W, H, "".join(parts)))
    Path(out_path).write_text(svg, encoding="utf-8")
    return Path(out_path)
