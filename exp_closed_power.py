import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "package"))
# -*- coding: utf-8 -*-
"""Closed testing vs k/alpha threshold: the spread-evidence cell, measured.

Five components, each mildly harmful, so pruning evidence is spread across the family
rather than concentrated in one switch - the regime where the step-down closed test's
dominance over the union-bound threshold is strict. Synthetic outcomes (mirror pairs,
task effect cancels by construction), fixed seed, replications; writes
exp_closed_power.json for build-time injection.

  python exp_closed_power.py
"""
import json, random, sys
from pathlib import Path


from mirrorcut import MirrorScreen

K, EFF, ROWS, REPS, ALPHA = 5, 0.06, 600, 200, 0.05
NAMES = ["c%d" % i for i in range(K)]


def run_one(seed, eff=EFF, rows=ROWS):
    rng = random.Random(seed)
    sc = MirrorScreen(NAMES, alpha=ALPHA, seed=seed)
    for _ in range(rows):
        cfg = {n: rng.random() < 0.5 for n in NAMES}
        # each ON component subtracts EFF from success probability
        p_plus = min(max(0.5 - eff * sum(1 for n in NAMES if cfg[n]) / 2.0, 0.02), 0.98)
        p_minus = min(max(0.5 - eff * sum(1 for n in NAMES if not cfg[n]) / 2.0, 0.02), 0.98)
        y = 1.0 if rng.random() < p_plus else 0.0
        ym = 1.0 if rng.random() < p_minus else 0.0
        sc.feed(cfg, y, ym, task_id=None)
    v = sc.verdicts()
    bonf = sum(1 for w in v.values() if w["verdict"] == "pruned")
    closed = sum(1 for ok in sc.closed_test("down").values() if ok)
    return bonf, closed


def main():
    cells = []
    for eff in (0.10, 0.15, 0.20, 0.30):
        for rows in (400, 800):
            tb = tc = wins = 0
            for r in range(REPS):
                b, c = run_one(20260820 + r, eff, rows)
                tb += b
                tc += c
                wins += 1 if c > b else 0
            cells.append({"effect": eff, "rows": rows,
                          "mean_pruned_bonferroni": round(tb / REPS, 2),
                          "mean_certified_closed": round(tc / REPS, 2),
                          "share_reps_closed_strictly_more": round(wins / REPS, 3)})
            print(cells[-1])
    head = max(cells, key=lambda c: c["mean_certified_closed"] - c["mean_pruned_bonferroni"])
    out = {"k": K, "reps": REPS, "alpha": ALPHA, "cells": cells, "headline": head}
    Path(__file__).with_name("exp_closed_power.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    print("headline:", json.dumps(head))


if __name__ == "__main__":
    main()
