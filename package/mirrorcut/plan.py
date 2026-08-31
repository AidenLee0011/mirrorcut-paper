# -*- coding: utf-8 -*-
"""Budget planning: how many rows until this tells you something.

    from mirrorcut import plan
    plan(k=5, effect=0.10, cost_per_invocation=0.03)

Simulates the calibrated world (replay flip 0.117, champion pass 0.491 - both measured
on a production agent; override them with your own pilot numbers) and reports the
distribution of rows-to-first-decision and rows-to-full-recovery for an effect of the
size you care about. Numbers are simulation medians, not guarantees; run a pilot for
your own task mix.
"""
from __future__ import annotations

import random

from .core import MirrorScreen

__all__ = ["plan"]


def plan(k=5, effect=0.10, alpha=0.05, n_active=1, reps=60, max_rows=8000,
         cost_per_invocation=None, churn=0.117, base=0.491, spread=4.0, seed=0):
    """Simulate rows-to-decision for k switches of which n_active carry `effect`.

    Returns a dict with quartiles of rows to the first decision and to recovery of all
    active switches (None where the budget ran out), plus invocations and, if a cost is
    given, dollars.
    """
    first, full = [], []
    for rep in range(reps):
        rng = random.Random(seed * 100003 + rep)
        tasks = [rng.betavariate(spread * base, spread * (1 - base)) for _ in range(200)]
        screen = MirrorScreen(["c%d" % i for i in range(k)], alpha=alpha, seed=rep)
        active = {"c%d" % i for i in range(n_active)}
        f = None
        got = None
        for row in range(max_rows):
            if screen.done:
                break
            cfg, mir = screen.next_pair(task_id=row)
            q = tasks[rng.randrange(len(tasks))]

            def y(c):
                fail = 1.0 - q
                for name in active:
                    if c[name]:
                        fail *= 1.0 - effect
                p = (1.0 - churn) * (1.0 - fail) + churn / 2.0
                return 1 if rng.random() < p else 0

            screen.observe(y(cfg), y(mir))
            s = screen.summary()
            if f is None and (s["admitted"] or s["pruned"]):
                f = screen.rows
            if got is None and active <= set(s["admitted"]):
                got = screen.rows
                break
        first.append(f)
        full.append(got)

    def q(xs):
        xs = sorted(x for x in xs if x is not None)
        if not xs:
            return None
        return {"p25": xs[len(xs) // 4], "median": xs[len(xs) // 2],
                "p75": xs[3 * len(xs) // 4]}

    med = q(full)
    out = {"k": k, "effect": effect, "alpha": alpha, "n_active": n_active,
           "reps": reps, "rows_to_first_decision": q(first),
           "rows_to_all_active_admitted": med,
           "undecided_share_pct": round(100.0 * sum(1 for x in full if x is None)
                                        / len(full), 1)}
    if med and cost_per_invocation is not None:
        out["cost_at_median"] = round(2 * med["median"] * cost_per_invocation, 2)
    return out
