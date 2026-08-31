# -*- coding: utf-8 -*-
"""One runnable check. It fails if the guarantee or the power breaks.

  python test_mirrorcut.py           quick
  python tests/test_calibration.py 400       the numbers quoted in the README
"""
from __future__ import annotations
import random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mirrorcut import MirrorScreen, ADMITTED

CHURN = 0.117          # measured replay flip rate of a production agent
BASE = 0.491           # measured pass rate of the champion


def world(cfg, task_difficulty, effects, interaction=None, rng=None):
    fail = 1.0 - task_difficulty
    for name, gain in effects.items():
        if cfg[name]:
            fail *= 1.0 - gain
    p = 1.0 - fail
    if interaction:
        a, b, delta = interaction
        if cfg[a] and cfg[b]:
            p += delta
    p = min(1.0, max(0.0, p))
    p = (1.0 - CHURN) * p + CHURN * 0.5
    return 1 if rng.random() < p else 0


def trial(seed, effects, interaction, budget=6400, names=None):
    rng = random.Random(seed * 2 + 1)          # simulator stream, distinct from the screen's
    names = names or ["compress", "tools", "retry", "reflect", "memory"]
    screen = MirrorScreen(names, seed=seed)
    tasks = [rng.betavariate(4 * BASE, 4 * (1 - BASE)) for _ in range(200)]
    while screen.invocations + 2 <= budget and not screen.done:
        cfg, mir = screen.next_pair()
        t = tasks[rng.randrange(len(tasks))]
        screen.observe(world(cfg, t, effects, interaction, rng),
                       world(mir, t, effects, interaction, rng))
    return {n: v["verdict"] for n, v in screen.verdicts().items()}


def main(reps=120):
    names = ["compress", "tools", "retry", "reflect", "memory"]
    live = {"compress": 0.15, "tools": 0.15}
    inert = [n for n in names if n not in live]

    false_admit = 0
    for r in range(reps):
        v = trial(1000 + r, {}, None)
        if any(v[n] == ADMITTED for n in names):
            false_admit += 1
    fwer = 100.0 * false_admit / reps
    print("global null       family-wise error %.1f%% over %d runs (nominal 5%%)" % (fwer, reps))

    recovered = 0
    for r in range(reps):
        v = trial(2000 + r, live, None)
        recovered += sum(1 for n in live if v[n] == ADMITTED)
    rec = 100.0 * recovered / (reps * len(live))
    print("live effects      recovered %.1f%% of the components that matter" % rec)

    charged = 0
    for r in range(reps):
        v = trial(3000 + r, live, ("compress", "tools", 0.12))
        if any(v[n] == ADMITTED for n in inert):
            charged += 1
    mis = 100.0 * charged / reps
    print("with interaction  inert component admitted %.1f%% of runs" % mis)

    assert fwer <= 10.0, "family-wise error is not controlled: %.1f%%" % fwer
    assert rec >= 70.0, "power collapsed: %.1f%%" % rec
    assert mis <= 10.0, "interaction charged to an inert component: %.1f%%" % mis
    print("ok")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
