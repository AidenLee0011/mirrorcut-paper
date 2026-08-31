# -*- coding: utf-8 -*-
"""Reproduce the README quickstart output, deterministically.

  python -m mirrorcut demo      (or: python -m mirrorcut.demo)

Three switches on a simulated agent calibrated to a production system (replay flip
0.117, champion pass rate 0.491 - measured, not chosen): a retry rule that genuinely
helps, a reflection step that does nothing, and a strictness guardrail that genuinely
hurts. Seed fixed, so the printed summary is byte-identical run to run - the README
quotes this output, and brand/demo.svg is this same run drawn as evidence paths.
"""
from __future__ import annotations
import random

from .core import MirrorScreen

CHURN = 0.117
BASE = 0.491
SEED = 7
NAMES = ["retry", "reflect", "strict_guardrail"]
ROWS = 600


def world(cfg, q, rng):
    fail = 1.0 - q
    if cfg["retry"]:
        fail *= 1.0 - 0.22            # genuinely helps
    if cfg["strict_guardrail"]:
        fail *= 1.30                  # genuinely hurts
    p = max(0.0, min(1.0, (1.0 - CHURN) * (1.0 - fail) + CHURN / 2.0))
    return 1 if rng.random() < p else 0


def run_screen(rows=ROWS, seed=SEED):
    rng = random.Random(seed * 2 + 1)
    tasks = [rng.betavariate(4 * BASE, 4 * (1 - BASE)) for _ in range(200)]
    screen = MirrorScreen(NAMES, seed=seed)
    for i in range(rows):
        if screen.done:
            break
        cfg, mirror = screen.next_pair(task_id=i)
        q = tasks[rng.randrange(len(tasks))]
        screen.observe(world(cfg, q, rng), world(mirror, q, rng))
    return screen


def main():
    screen = run_screen()
    v = screen.verdicts()
    for name in NAMES:
        r = dict(v[name])
        if r["verdict"] == "active":
            r["verdict"] = "undecided"
        where = (" at row %d" % r["decided_at_row"]) if r["decided_at_row"] else ""
        print("%-18s %-10s%s   effect on pass rate %+0.1fpp" %
              (name, r["verdict"], where, r["effect_pp"] or 0.0))
    s = screen.summary()
    print("rows %d   invocations %d   (at $0.01/run: $%.0f)"
          % (s["rows"], s["invocations"], s["invocations"] * 0.01))
    return s


if __name__ == "__main__":
    main()
