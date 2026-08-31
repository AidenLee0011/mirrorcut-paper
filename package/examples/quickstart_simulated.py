# -*- coding: utf-8 -*-
"""Quickstart on a simulated agent: screen five switches, two of which actually work.

  python examples/quickstart_simulated.py

Runs in seconds, no model calls: `run()` below is a calibrated stand-in for your agent
(replay flip 0.117, champion pass rate 0.491 - both measured on a production system).
Swap `run()` for your agent and the rest is unchanged.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mirrorcut import MirrorScreen

CHURN, BASE = 0.117, 0.491
EFFECTS = {"compress": 0.15, "tools": 0.15}   # the two switches that genuinely help
rng = random.Random(7)
tasks = [rng.betavariate(4 * BASE, 4 * (1 - BASE)) for _ in range(200)]


def run(task_difficulty, cfg):
    fail = 1.0 - task_difficulty
    for name, gain in EFFECTS.items():
        if cfg[name]:
            fail *= 1.0 - gain
    p = (1.0 - CHURN) * (1.0 - fail) + CHURN / 2.0
    return 1 if rng.random() < p else 0


screen = MirrorScreen(["compress", "tools", "retry", "reflect", "memory"], seed=7)
for i in range(3000):
    if screen.done:
        break
    cfg, mirror = screen.next_pair(task_id=i)
    t = tasks[rng.randrange(len(tasks))]
    screen.observe(run(t, cfg), run(t, mirror))

s = screen.summary()
print(s)
assert set(s["admitted"]) == {"compress", "tools"}, s
assert not (set(s["pruned"]) | set(s["retired"])) & {"compress", "tools"}, s
print("ok: the two real switches were admitted, nothing real was thrown away")
