# -*- coding: utf-8 -*-
"""Choose paired or unpaired screening from a pilot, before spending the budget.

The mirror removes the task effect from every increment at the price of two invocations
per row. Whether that trade pays depends on one quantity: the spread of task difficulty.
This module computes the manuscript's Section 6 criterion exactly - the expected
log-growth per invocation of each arm's e-process, under the actual clipped plug-in bet -
from a pilot you run yourself, and recommends the arm with the larger growth.

    from mirrorcut import pairing_gain

    # pass rates of your current (champion) configuration, one per task,
    # each estimated from a few repeats of the same task
    report = pairing_gain([0.9, 0.4, 0.7, 0.95, 0.2], effect=0.1)
    report["recommend"]     # "mirror" or "unpaired"
    report["ratio"]         # mirror growth / unpaired growth, per invocation

Across the manuscript's paired-versus-unpaired grid (Tables 5-6 there) the prediction's
sign was resolved by the data in six of seven cells and consistent with a tie in the
seventh; the checks share the simulator's generative model, so they are model-consistency,
not external validation. On the manuscript's live deployment the criterion, computed from
noise-corrected per-task rates (see `shrunk_rates`), recommended the mirror; the exact
figure is built from the run ledger in the manuscript, not restated here.
"""
from __future__ import annotations

import math

__all__ = ["pairing_gain", "shrunk_rates"]


def _clip01(x):
    return max(0.0, min(1.0, x))


def pairing_gain(task_pass_rates, effect=0.1, bet_cap=0.45, bet_floor=0.10):
    """Exact per-invocation log-growth of the mirror and unpaired e-processes.

    task_pass_rates : per-task pass probabilities of the champion configuration, from a
                      pilot (repeat each task a few times and average). Their spread is
                      the only quantity the choice depends on.
    effect          : smallest per-component effect worth detecting, as the share of the
                      remaining failure mass a helpful component removes (manuscript
                      calibration: 0.15 measured, 0.1 a conservative default).

    Returns a dict with per-arm growth, their ratio (mirror / unpaired), the
    recommendation, and the pilot size. Growth is computed from the exact increment
    distribution under the pilot's empirical task mixture, with the same clipped plug-in
    bet the screen runs, so the recommendation and the screen cannot disagree about the
    betting rule.

    Two simplifications, stated rather than discovered. The computation models a single
    active component: the other components' main effects enter both arms' increments as
    additional mean-zero noise (odd-order terms survive the mirror difference), which this
    chooser omits; when several components carry large effects the true growth of both
    arms is lower than computed, and the ratio moves second-order. And the generative
    assumption (a helpful component removes `effect` of the remaining failure mass) is
    the manuscript's; on your deployment the chooser is a calibrated prediction, not a
    guarantee. Pilot guidance: fewer than 8 tasks estimates the spread poorly - the
    function runs but flags it in `note`; 20+ tasks with 3+ repeats each is a sound pilot.
    """
    qs = [float(q) for q in task_pass_rates]
    if not qs:
        raise ValueError("empty pilot")
    if any(not (0.0 <= q <= 1.0) for q in qs):
        raise ValueError("pass rates must lie in [0, 1]")
    if not (0.0 < effect < 1.0):
        raise ValueError("effect must be in (0, 1)")
    w = 1.0 / len(qs)

    def p_of(q, on):
        fail = 1.0 - q
        if on:
            fail *= 1.0 - effect
        return _clip01(1.0 - fail)

    out = {}
    for arm in ("mirror", "unpaired"):
        dist = {}
        if arm == "mirror":
            for q in qs:
                for xi in (1, -1):
                    p1, p2 = p_of(q, xi == 1), p_of(q, xi != 1)
                    for y1 in (0, 1):
                        for y2 in (0, 1):
                            g = xi * (y1 - y2) / 2.0
                            pr = 0.5 * w * (p1 if y1 else 1 - p1) * (p2 if y2 else 1 - p2)
                            dist[g] = dist.get(g, 0.0) + pr
        else:
            centre = sum(w * (p_of(q, True) + p_of(q, False)) / 2.0 for q in qs)
            for q in qs:
                for xi in (1, -1):
                    p1 = p_of(q, xi == 1)
                    for y in (0, 1):
                        g = xi * (y - centre)
                        pr = 0.5 * w * (p1 if y else 1 - p1)
                        dist[g] = dist.get(g, 0.0) + pr
        mu = sum(g * pr for g, pr in dist.items())
        var = sum(g * g * pr for g, pr in dist.items()) - mu * mu
        lam = max(0.0, min(bet_cap, mu / (var + mu * mu + bet_floor)))
        growth = sum(pr * math.log(1.0 + lam * g) for g, pr in dist.items())
        out[arm] = growth / (2.0 if arm == "mirror" else 1.0)

    ratio = (out["mirror"] / out["unpaired"]) if out["unpaired"] > 0 else float("inf")
    return {"mirror_growth_per_invocation": out["mirror"],
            "unpaired_growth_per_invocation": out["unpaired"],
            "ratio": ratio,
            "recommend": "mirror" if ratio > 1.0 else "unpaired",
            "n_tasks": len(qs),
            "note": ("pilot has fewer than 8 tasks; the spread estimate is weak"
                     if len(qs) < 8 else "")}


def shrunk_rates(task_outcomes):
    """Noise-corrected per-task pass rates for `pairing_gain`, from raw pilot outcomes.

    task_outcomes : list of per-task outcome lists (each 0/1 or [0,1] scores, 2+ each).

    A task mean from m draws carries binomial noise p(1-p)/m; feeding raw means into
    `pairing_gain` inflates the apparent between-task spread and biases the criterion
    toward the mirror. This helper subtracts the estimated noise component and shrinks
    each mean toward the grand mean accordingly (variance decomposition; shrink factor
    sqrt(Var_t / Var_obs)). With many repeats per task the correction vanishes.
    """
    tasks = [list(map(float, v)) for v in task_outcomes if len(v) >= 2]
    if len(tasks) < 2:
        raise ValueError("need 2+ tasks with 2+ outcomes each")
    means = [sum(v) / len(v) for v in tasks]
    g = sum(means) / len(means)
    obs = sum((m - g) ** 2 for m in means) / len(means)
    noise = sum((len(v) / (len(v) - 1)) * (sum(v) / len(v)) * (1 - sum(v) / len(v)) / len(v)
                for v in tasks) / len(tasks)
    var_t = max(0.0, obs - noise)
    lam = (var_t / obs) ** 0.5 if obs > 0 else 0.0
    return [min(1.0, max(0.0, g + lam * (m - g))) for m in means]
