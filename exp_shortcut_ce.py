# -*- coding: utf-8 -*-
"""Distributional counterexample: the sorted full-tail shortcut breaks FWER (P41.2).

Construction (three hypotheses, alpha = 1/6, threshold 1/alpha = 6):
  disjoint events A, B with P(A) = P(B) = 1/10;
  E1 = 10 on A else 0  (true null: E[E1] = 1),
  E2 = 10 on B else 0  (true null: E[E2] = 1),
  E3 = 9 constant      (false null, unconstrained).
On A the sorted e-values are (10, 9, 0): the full-tail shortcut checks the rank-1..3
mean 19/3 = 6.33 >= 6 and rejects the top component = H1, a true null; symmetrically
H2 on B. Shortcut FWER = P(A) + P(B) = 0.200 > 1/6 = 0.1667.
The exact closure blocks: subset {H1, H2} has mean (10+0)/2 = 5 < 6, so no true null
is ever rejected (closure FWER = 0 here). Each E_i is realised as the terminal value
of a single-bet nonnegative supermartingale, so the example lives inside the paper's
e-process setting.

  python exp_shortcut_ce.py   -> exp_shortcut_ce.json (exact + 200k MC check)
"""
from __future__ import annotations
import json, random
from fractions import Fraction as F
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALPHA = F(1, 6)
THR = 1 / ALPHA  # 6
P_A = P_B = F(1, 10)


def shortcut_rejects(e, thr):
    """Sorted full-tail: reject rank m while mean of ranks m..k clears thr."""
    order = sorted(range(len(e)), key=lambda i: -e[i])
    rejected = []
    for m in range(len(e)):
        tail = [e[order[j]] for j in range(m, len(e))]
        if F(sum(tail), len(tail)) >= thr:
            rejected.append(order[m])
        else:
            break
    return rejected


def closure_rejects(e, thr):
    k = len(e)
    out = []
    for j in range(k):
        ok = True
        for mask in range(1, 1 << k):
            if not (mask >> j) & 1:
                continue
            sub = [e[i] for i in range(k) if (mask >> i) & 1]
            if F(sum(sub), len(sub)) < thr:
                ok = False
                break
        if ok:
            out.append(j)
    return out


def main():
    true_nulls = {0, 1}
    worlds = [("A", P_A, [F(10), F(0), F(9)]),
              ("B", P_B, [F(0), F(10), F(9)]),
              ("rest", 1 - P_A - P_B, [F(0), F(0), F(9)])]
    assert sum(p * e[0] for _, p, e in worlds) == 1, "E1 not a valid e-value"
    assert sum(p * e[1] for _, p, e in worlds) == 1, "E2 not a valid e-value"
    fwer_short = sum(p for _, p, e in worlds
                     if set(shortcut_rejects(e, THR)) & true_nulls)
    fwer_clos = sum(p for _, p, e in worlds
                    if set(closure_rejects(e, THR)) & true_nulls)
    # MC sanity (the exact computation above is the proof; this is a smoke check)
    rng = random.Random(0)
    n, bad = 200_000, 0
    for _ in range(n):
        u = rng.random()
        e = [10.0, 0.0, 9.0] if u < 0.1 else ([0.0, 10.0, 9.0] if u < 0.2 else [0.0, 0.0, 9.0])
        if set(shortcut_rejects([F(x) for x in e], THR)) & true_nulls:
            bad += 1
    out = {"alpha": float(ALPHA), "threshold": float(THR),
           "fwer_shortcut_exact": float(fwer_short),
           "fwer_closure_exact": float(fwer_clos),
           "fwer_shortcut_mc": bad / n, "mc_n": n,
           "e_values": {"E1": "10 on A (P=0.1) else 0", "E2": "10 on B (P=0.1) else 0",
                        "E3": "9 constant (false null)"}}
    assert fwer_short == F(1, 5) and fwer_short > ALPHA
    assert fwer_clos == 0
    (HERE / "exp_shortcut_ce.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
