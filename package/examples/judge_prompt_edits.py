# -*- coding: utf-8 -*-
"""Judging a self-improvement loop: accept proposed prompt edits with error control.

  python examples/judge_prompt_edits.py

A proposer (SkillOpt/GEPA-style) emits candidate edits; the usual acceptance rule -
adopt-if-better on a held-out point comparison - false-adopts almost every round at a
realistic replay flip rate. This example judges the same candidates with a screen at
alpha spent across rounds, and shows both outcomes on one simulated round.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mirrorcut import MirrorScreen

CHURN = 0.117
rng = random.Random(11)
EDITS = {"edit_%d" % i: 0.0 for i in range(8)}   # eight do-nothing edits
EDITS["edit_3"] = 0.15                            # one genuinely good one
EDITS["edit_6"] = 0.15                            # and another


def run(cfg):
    fail = 0.5
    for name, gain in EDITS.items():
        if cfg[name]:
            fail *= 1.0 - gain
    p = (1.0 - CHURN) * (1.0 - fail) + CHURN / 2.0
    return 1 if rng.random() < p else 0


# --- the broken rule: adopt-if-better per candidate, 320 runs per side
adopted = []
for name in EDITS:
    champ = sum(run({n: False for n in EDITS}) for _ in range(320))
    varnt = sum(run({n: n == name for n in EDITS}) for _ in range(320))
    if varnt > champ:
        adopted.append(name)
false_pos = [n for n in adopted if EDITS[n] == 0.0]
print("point comparison adopted %d edits, %d of them do nothing: %s"
      % (len(adopted), len(false_pos), false_pos))

# --- the controlled rule: one screen, alpha spent across 5 planned rounds
screen = MirrorScreen.for_rounds(list(EDITS), rounds=5, seed=11)
for i in range(6000):
    if screen.done:
        break
    cfg, mirror = screen.next_pair(task_id=i)
    screen.observe(run(cfg), run(mirror))
s = screen.summary()
print("screen admitted:", s["admitted"], " pruned:", s["pruned"])
assert set(s["admitted"]) <= {"edit_3", "edit_6"}, s
print("ok: nothing inert was admitted (family-wise alpha/5 held)")
