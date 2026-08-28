# -*- coding: utf-8 -*-
# E1b. Mirror pairing with independent levels, measured against the rotation designs.
#
# A row draws its levels independently, is executed at x and at -x on the same task, and the
# per-component signal is g_i = x_i (y_plus - y_minus) / 2. Every even-order term of the
# response cancels in that difference, interactions included, so the signal is free of
# two-factor aliasing without any design resolution argument. Cross terms of odd order have
# mean zero because the levels are independent, so the increment is a valid e-process step.
from __future__ import annotations
import json, math, random, sys, time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "oss" / "veto_loop"))
import exp_screen as E
from mirror import RowEProcess, ACTIVE, ADMITTED, PRUNED

TASKS = E.TASKS
ALPHA = E.ALPHA


def run_rademacher(k, budget, rng, effect, inter, active, kappa, sequential=True):
    pool = E.task_pool(rng, kappa)
    proc = RowEProcess(k, alpha=ALPHA)
    s = [0.0] * k
    ss = [0.0] * k
    n = 0
    calls = 0
    while calls + 2 <= budget:
        forced = {i: (1 if st == ADMITTED else -1) for i, st in enumerate(proc.state)
                  if st != ACTIVE}
        x = [1 if rng.random() < 0.5 else -1 for _ in range(k)]
        for i, v in forced.items():
            x[i] = v
        mir = [(-v if i not in forced else v) for i, v in enumerate(x)]
        q = pool[rng.randrange(TASKS)]
        y_p = 1 if rng.random() < E.p_pass(q, x, effect, inter, active) else 0
        y_m = 1 if rng.random() < E.p_pass(q, mir, effect, inter, active) else 0
        calls += 2
        d = (y_p - y_m) / 2.0
        sig = [x[i] * d for i in range(k)]
        n += 1
        for i in range(k):
            s[i] += sig[i]
            ss[i] += sig[i] * sig[i]
        if sequential:
            proc.observe_row(sig)
            if proc.done:
                break
    if sequential:
        return {"admitted": proc.admitted(), "calls": calls, "early": proc.done,
                "est": [s[i] / max(n, 1) for i in range(k)], "proc": proc}
    adm, est = [], []
    for i in range(k):
        mu = s[i] / max(n, 1)
        var = max(ss[i] / max(n, 1) - mu * mu, 1e-12)
        est.append(mu)
        if n >= 2 and mu / math.sqrt(var / n) > E.Z_BONF[k]:
            adm.append(i)
    return {"admitted": adm, "calls": calls, "early": False, "est": est}


def run_random_unpaired(k, budget, rng, effect, inter, active, kappa, sequential):
    """Reviewer-demanded attribution baselines. Levels are drawn iid per row, one invocation
    per row, no mirror. The signal for component i is x_i (y - ybar), centred with the
    running mean of past outcomes (predictable, so the e-process stays valid). Randomisation
    alone already removes alias bias; what it does not remove is the task effect, which
    stays in the increment and costs power. That cost is the point of this arm."""
    pool = E.task_pool(rng, kappa)
    n_rows = budget
    s = [0.0] * k
    ss = [0.0] * k
    ybar_sum = 0.0
    if sequential:
        from mirror import RowEProcess
        proc = RowEProcess(k, alpha=E.ALPHA)
    n = 0
    est_n = 0
    for j in range(n_rows):
        x = [1 if rng.random() < 0.5 else -1 for _ in range(k)]
        q = pool[rng.randrange(E.TASKS)]
        y = 1 if rng.random() < E.p_pass(q, x, effect, inter, active) else 0
        centre = (ybar_sum / n) if n else 0.5      # predictable centring
        n += 1
        ybar_sum += y
        sig = [x[i] * (y - centre) for i in range(k)]
        est_n += 1
        for i in range(k):
            s[i] += sig[i]        # centred signal, same statistic as the sequential twin
            ss[i] += sig[i] * sig[i]
        if sequential:
            proc.observe_row([max(-1.0, min(1.0, v)) for v in sig])
            if proc.done:
                break
    if sequential:
        return {"admitted": proc.admitted(), "calls": n, "early": proc.done,
                "est": [s[i] / max(n, 1) for i in range(k)]}
    adm, est = [], []
    for i in range(k):
        mu = s[i] / max(n, 1)
        var = max(ss[i] / max(n, 1) - mu * mu, 1e-9)   # empirical
        est.append(mu)
        if n >= 2 and mu / math.sqrt(var / n) > E.Z_BONF[k]:
            adm.append(i)
    return {"admitted": adm, "calls": n, "early": False, "est": est}


def run_spending(k, x, budget, rng, effect, inter, active, kappa, looks=8):
    """The corrected interim baseline the naive peeking arm lacks: the same repeated looks,
    but each look is tested at Z for level alpha/(k*looks), a Bonferroni spend over looks.
    Group-sequential in its simplest defensible form."""
    import statistics
    pool = E.task_pool(rng, kappa)
    m = len(x)
    n_rows = budget
    hi = [[0.0, 0] for _ in range(k)]
    lo = [[0.0, 0] for _ in range(k)]
    from math import sqrt, log
    # z for one-sided alpha/(k*looks) via a coarse table is fragile; use the exact inverse
    import math as _m
    def probit(p):
        # Acklam rational approximation
        a=[-3.969683028665376e+01,2.209460984245205e+02,-2.759285104469687e+02,1.383577518672690e+02,-3.066479806614716e+01,2.506628277459239e+00]
        b=[-5.447609879822406e+01,1.615858368580409e+02,-1.556989798598866e+02,6.680131188771972e+01,-1.328068155288572e+01]
        c=[-7.784894002430293e-03,-3.223964580411365e-01,-2.400758277161838e+00,-2.549732539343734e+00,4.374664141464968e+00,2.938163982698783e+00]
        d=[7.784695709041462e-03,3.224671290700398e-01,2.445134137142996e+00,3.754408661907416e+00]
        pl=0.02425
        if p<pl:
            q=_m.sqrt(-2*_m.log(p)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        if p>1-pl:
            q=_m.sqrt(-2*_m.log(1-p)); return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        q=p-0.5; r=q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q/(((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    zcrit = -probit(E.ALPHA / (k * looks))
    every = max(1, n_rows // looks)
    hit = set()
    for j in range(n_rows):
        q = pool[rng.randrange(E.TASKS)]
        cfg = x[j % m]
        y = 1 if rng.random() < E.p_pass(q, cfg, effect, inter, active) else 0
        for i in range(k):
            b_ = hi[i] if cfg[i] == 1 else lo[i]
            b_[0] += y
            b_[1] += 1
        if (j + 1) % every == 0:
            for i in range(k):
                if hi[i][1] < 5 or lo[i][1] < 5:
                    continue
                mh = hi[i][0] / hi[i][1]
                ml = lo[i][0] / lo[i][1]
                se = _m.sqrt(mh * (1 - mh) / hi[i][1] + ml * (1 - ml) / lo[i][1]) or 1e-9
                if (mh - ml) / se > zcrit:
                    hit.add(i)
            if hit:
                est = [0.0] * k
                return {"admitted": sorted(hit), "calls": j + 1, "early": True, "est": est}
    return {"admitted": [], "calls": n_rows, "early": False, "est": [0.0] * k}



ARMS = {
 "full/unpaired/fixed": lambda k, d, b, g, e, i, a, kp: E.run_fixed(k, d["full"], b, g, e, i, a, False, kp),
 "res3/unpaired/fixed": lambda k, d, b, g, e, i, a, kp: E.run_fixed(k, d["res3"], b, g, e, i, a, False, kp),
 "res4/unpaired/peek": lambda k, d, b, g, e, i, a, kp: E.run_fixed(k, d["res4"], b, g, e, i, a, False, kp, peek=40),
 "res4/paired/eproc": lambda k, d, b, g, e, i, a, kp: E.run_eproc(k, d["res4"], b, g, e, i, a, kp),
 "mirror/rademacher/fixed": lambda k, d, b, g, e, i, a, kp: run_rademacher(k, b, g, e, i, a, kp, False),
 "mirror/rademacher/eproc": lambda k, d, b, g, e, i, a, kp: run_rademacher(k, b, g, e, i, a, kp, True),
 "rand/unpaired/fixed": lambda k, d, b, g, e, i, a, kp: run_random_unpaired(k, b, g, e, i, a, kp, False),
 "rand/unpaired/eproc": lambda k, d, b, g, e, i, a, kp: run_random_unpaired(k, b, g, e, i, a, kp, True),
 "res4/unpaired/spending": lambda k, d, b, g, e, i, a, kp: run_spending(k, d["res4"], b, g, e, i, a, kp),
}


def cell(k, effect, inter, kappa, budget, reps):
    active = (0, 1)
    if inter == "cond_null":
        # component 1 non-positive at every stage: marginal 2*(-0.02) < 0 and conditional on
        # component 0 committed at +1, 2*(-0.02 - 0.02) < 0. The intersection null is TRUE,
        # so the theorem promises admission of component 1 at most alpha.
        inter = ("sf", -0.02, -0.02)
        active = (0,)
    elif inter == "sign_flip":
        # marginal effect of component 1 is +2*0.03, conditional on component 0 committed at
        # +1 it is 2*(0.03-0.06) < 0: the running hypothesis changes sign mid-run
        inter = ("sf", 0.03, -0.06)
        active = (0,)
    elif inter == "pin02":
        # one strong component that decides early, interacting with a component whose
        # marginal effect is zero: the pinned-estimand case the theory must own
        inter = ("sym", 0, 2, 0.06)
        active = (0,)
    inert = tuple(i for i in range(k) if i not in active)
    d = E.designs(k)
    ac3 = E.alias_col(d["res3"], k)
    if isinstance(inter, tuple):
        ac3 = 1 if inter[0] == "sf" else inter[2]
    out = {}
    for name, fn in ARMS.items():
        acc = {"rec": 0, "fwer": 0, "alias": 0, "calls": 0, "early": 0, "est_alias": 0.0,
               "rec_sq": 0.0}
        for rep in range(reps):
            rng = random.Random(hash((name, k, effect, inter, kappa, budget, rep)) & 0xFFFFFFFF)
            r = fn(k, d, budget, rng, effect, inter, active, kappa)
            adm = set(r["admitted"])
            fr = len(adm & set(active)) / max(len(active), 1)
            acc["rec"] += len(adm & set(active))
            acc["rec_sq"] += fr * fr
            acc["fwer"] += 1 if adm & set(inert) else 0
            acc["alias"] += 1 if ac3 in adm else 0
            acc["est_alias"] += r["est"][ac3]
            acc["calls"] += r["calls"]
            acc["early"] += 1 if r["early"] else 0
        n_rec = reps * len(active)
        p_rec = acc["rec"] / n_rec
        p_fw = acc["fwer"] / reps
        mean_fr = acc["rec"] / (reps * max(len(active), 1))
        var_fr = max(acc["rec_sq"] / reps - mean_fr * mean_fr, 0.0)   # clustered at run level
        out[name] = {"recovery_pct": round(100 * p_rec, 1),
                     "recovery_se": round(100 * math.sqrt(var_fr / reps), 1),
                     "fwer_pct": round(100 * p_fw, 1),
                     "fwer_se": round(100 * math.sqrt(max(p_fw, 1e-9) * (1 - p_fw) / reps), 1),
                     "alias_admit_pct": round(100 * acc["alias"] / reps, 1),
                     "est_alias_col": round(acc["est_alias"] / reps, 4),
                     "calls_avg": round(acc["calls"] / reps, 1),
                     "early_stop_pct": round(100 * acc["early"] / reps, 1)}
    return out


def main(reps=300):
    t0 = time.time()
    res = {"params": {"reps": reps, "churn": E.CHURN, "fail_share": E.FAIL_SHARE,
                      "tasks": TASKS, "alpha": ALPHA}, "cells": {}}
    for k in (5, 10):
        for kappa, ktag in ((None, "homog"), (4.0, "hetero"), (1.0, "xhetero")):
            for label, eff, inter in (("null", 0.0, 0.0), ("main", 0.15, 0.0),
                                      ("interference", 0.15, -0.12), ("synergy", 0.15, 0.12),
                                      ("pinned_inter", 0.20, "pin02"),
                                      ("sign_flip", 0.20, "sign_flip"),
                                      ("cond_null", 0.20, "cond_null")):
                for b in (400, 1600, 6400):
                    key = "k%d|%s|%s|%d" % (k, label, ktag, b)
                    res["cells"][key] = cell(k, eff, inter, kappa, b, reps)
                    print("%-30s %6.1fs" % (key, time.time() - t0), flush=True)
    (_HERE / "exp_mirror.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    hdr = "%-26s%-26s%9s%8s%11s%9s" % ("cell", "arm", "recov%", "FWER%", "aliasAdm%", "calls")
    print(hdr)
    print("-" * len(hdr))
    for ck, a in res["cells"].items():
        for name, v in a.items():
            print("%-26s%-26s%9s%8s%11s%9s" % (ck, name, v["recovery_pct"], v["fwer_pct"],
                                               v["alias_admit_pct"], v["calls_avg"]))
    for ck, a in res["cells"].items():
        if "|null|" in ck:
            for name in ("mirror/rademacher/eproc", "res4/paired/eproc"):
                assert a[name]["fwer_pct"] <= 12.0, (ck, name, a[name])
    print("")
    print("self-check ok  %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
