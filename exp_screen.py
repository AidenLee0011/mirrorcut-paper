# -*- coding: utf-8 -*-
# E1. Component screening for agent scaffolds.
# Three method axes are separated so that each price is attributable:
#   design    full | res3 (fractional, Resolution III) | res4 (fold-over, Resolution IV)
#   pairing   paired (champion and variant on the same row, 2 calls) | unpaired (1 call)
#   inference fixed (z test, one-sided Bonferroni over k) | eproc (anytime-valid e-process)
# Every arm receives the same number of model invocations.
from __future__ import annotations
import json, math, random, sys, time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[1] / "oss" / "veto_loop"))
from sfah import SFAHRound, SFAHConfig, design_matrix, is_orthogonal
sys.path.insert(0, str(_HERE))
from mirror import CycleEProcess, ACTIVE

CHURN = 0.117
FAIL_SHARE = 0.509
ALPHA = 0.05
Z_BONF = {5: 2.326, 10: 2.576}


def foldover(k):
    x = design_matrix(k)
    return x + [[-v for v in row] for row in x]


def full_design(k):
    return [[1 if (m >> i) & 1 else -1 for i in range(k)] for m in range(2 ** k)]


def alias_col(x, k, a=0, b=1):
    prod = [r[a] * r[b] for r in x]
    for c in range(k):
        col = [r[c] for r in x]
        if prod == col or prod == [-v for v in col]:
            return c
    return None


def designs(k):
    return {"full": full_design(k), "res3": design_matrix(k), "res4": foldover(k)}


TASKS = 200


def task_pool(rng, kappa):
    mean = 1.0 - FAIL_SHARE
    if kappa is None:
        return [mean] * TASKS
    return [rng.betavariate(kappa * mean, kappa * (1.0 - mean)) for _ in range(TASKS)]


def p_pass(q, cfg, effect, inter, active):
    fail_mass = 1.0 - q
    for i in active:
        if cfg[i] == 1:
            fail_mass *= 1.0 - effect
    p = 1.0 - fail_mass
    if isinstance(inter, tuple) and inter[0] == "sf":
        _, b1, g = inter
        p += b1 * cfg[1] + g * cfg[0] * cfg[1]   # theta_1 flips sign once c0 is committed
    elif isinstance(inter, tuple) and inter[0] == "sym":
        _, a, b, g = inter
        p += g * cfg[a] * cfg[b]          # pure interaction: zero marginal main effects
    elif isinstance(inter, tuple):
        a, b, delta = inter
        if cfg[a] == 1 and cfg[b] == 1:
            p += delta
    elif inter and cfg[active[0]] == 1 and cfg[active[1]] == 1:
        p += inter
    p = min(1.0, max(0.0, p))
    return (1.0 - CHURN) * p + CHURN * 0.5


def run_fixed(k, x, budget, rng, effect, inter, active, paired, kappa, peek=0):
    """Fixed-sample screening. peek>0 makes the analyst test every peek rows and stop
    at the first crossing, which is what practitioners actually do and what invalidates
    a fixed-sample threshold."""
    cost = 2 if paired else 1
    n_rows = budget // cost
    m = len(x)
    pool = task_pool(rng, kappa)
    champ = [-1] * k
    hit = set()
    if paired:
        s_ = [0.0] * k
        ss = [0.0] * k
        for j in range(n_rows):
            q = pool[rng.randrange(TASKS)]
            cfg = x[j % m]
            y_c = 1 if rng.random() < p_pass(q, champ, effect, inter, active) else 0
            y_v = 1 if rng.random() < p_pass(q, cfg, effect, inter, active) else 0
            d = y_v - y_c
            for i in range(k):
                g = cfg[i] * d
                s_[i] += g
                ss[i] += g * g
            n = j + 1
            if peek and n >= 40 and n % peek == 0:
                for i in range(k):
                    mu = s_[i] / n
                    var = max(ss[i] / n - mu * mu, 1e-12)
                    if mu / math.sqrt(var / n) > Z_BONF[k]:
                        hit.add(i)
                if hit:
                    return {"admitted": sorted(hit), "est": [v / n for v in s_],
                            "calls": n * cost, "early": True}
        adm, est = [], []
        for i in range(k):
            mu = s_[i] / n_rows
            var = max(ss[i] / n_rows - mu * mu, 1e-12)
            est.append(mu)
            if mu / math.sqrt(var / n_rows) > Z_BONF[k]:
                adm.append(i)
        return {"admitted": adm, "est": est, "calls": n_rows * cost, "early": False}
    hi = [[0.0, 0] for _ in range(k)]
    lo = [[0.0, 0] for _ in range(k)]

    def contrasts():
        out = []
        for i in range(k):
            if hi[i][1] < 5 or lo[i][1] < 5:
                out.append((0.0, 0.0))
                continue
            mh = hi[i][0] / hi[i][1]
            ml = lo[i][0] / lo[i][1]
            se = math.sqrt(mh * (1 - mh) / hi[i][1] + ml * (1 - ml) / lo[i][1]) or 1e-9
            out.append((mh - ml, (mh - ml) / se))
        return out

    for j in range(n_rows):
        q = pool[rng.randrange(TASKS)]
        cfg = x[j % m]
        y = 1 if rng.random() < p_pass(q, cfg, effect, inter, active) else 0
        for i in range(k):
            b = hi[i] if cfg[i] == 1 else lo[i]
            b[0] += y
            b[1] += 1
        n = j + 1
        if peek and n >= 40 and n % peek == 0:
            cs = contrasts()
            for i in range(k):
                if cs[i][1] > Z_BONF[k]:
                    hit.add(i)
            if hit:
                return {"admitted": sorted(hit), "est": [c[0] for c in cs],
                        "calls": n * cost, "early": True}
    cs = contrasts()
    adm = [i for i in range(k) if cs[i][1] > Z_BONF[k]]
    return {"admitted": adm, "est": [c[0] for c in cs], "calls": n_rows * cost, "early": False}


def run_eproc(k, x, budget, rng, effect, inter, active, kappa):
    rnd = SFAHRound(k, SFAHConfig(alpha=ALPHA))
    rnd.x = x
    rnd.m = len(x)
    pool = task_pool(rng, kappa)
    champ = [-1] * k
    calls, j = 0, 0
    while calls + 2 <= budget:
        q = pool[rng.randrange(TASKS)]
        cfg = rnd.configuration(j)
        y_c = 1 if rng.random() < p_pass(q, champ, effect, inter, active) else 0
        y_v = 1 if rng.random() < p_pass(q, cfg, effect, inter, active) else 0
        calls += 2
        rnd.observe(j, y_v - y_c)
        j += 1
        if rnd.done:
            break
    r = rnd.report()
    return {"admitted": r["admitted"], "calls": calls, "early": rnd.done,
            "est": [(sum(e.signals) / len(e.signals)) if e.signals else 0.0 for e in rnd.edits]}


def run_mirror(k, x, budget, rng, effect, inter, active, kappa, sequential=True):
    """Each row is executed at x and at -x on the same task; evidence is updated once per
    complete pass through the design. sequential=False turns the same data into a fixed
    sample z test, which isolates the price of the anytime-valid rule."""
    pool = task_pool(rng, kappa)
    m = len(x)
    proc = CycleEProcess(k, alpha=ALPHA)
    cyc_s = [0.0] * k
    cyc_ss = [0.0] * k
    n_cyc = 0
    calls = 0
    while calls + 2 * m <= budget:
        sig = [0.0] * k
        for j in range(m):
            q = pool[rng.randrange(TASKS)]
            cfg = list(x[j])
            for i in range(k):
                if proc.state[i] == 1:
                    cfg[i] = 1
                elif proc.state[i] == -1:
                    cfg[i] = -1
            mir = [-v for v in cfg]
            y_p = 1 if rng.random() < p_pass(q, cfg, effect, inter, active) else 0
            y_m = 1 if rng.random() < p_pass(q, mir, effect, inter, active) else 0
            calls += 2
            d = (y_p - y_m) / 2.0
            for i in range(k):
                sig[i] += x[j][i] * d
        sig = [v / m for v in sig]
        n_cyc += 1
        for i in range(k):
            cyc_s[i] += sig[i]
            cyc_ss[i] += sig[i] * sig[i]
        if sequential:
            proc.observe_cycle(sig)
            if proc.done:
                break
    if sequential:
        return {"admitted": proc.admitted(), "calls": calls, "early": proc.done,
                "est": [cyc_s[i] / max(n_cyc, 1) for i in range(k)]}
    adm, est = [], []
    for i in range(k):
        mu = cyc_s[i] / max(n_cyc, 1)
        var = max(cyc_ss[i] / max(n_cyc, 1) - mu * mu, 1e-12)
        est.append(mu)
        if n_cyc >= 2 and mu / math.sqrt(var / n_cyc) > Z_BONF[k]:
            adm.append(i)
    return {"admitted": adm, "calls": calls, "early": False, "est": est}


def arms(k):
    d = designs(k)
    return {
        "full/unpaired/fixed": lambda b, g, e, i, a, kp: run_fixed(k, d["full"], b, g, e, i, a, False, kp),
        "res3/unpaired/fixed": lambda b, g, e, i, a, kp: run_fixed(k, d["res3"], b, g, e, i, a, False, kp),
        "res4/unpaired/fixed": lambda b, g, e, i, a, kp: run_fixed(k, d["res4"], b, g, e, i, a, False, kp),
        "res4/paired/fixed": lambda b, g, e, i, a, kp: run_fixed(k, d["res4"], b, g, e, i, a, True, kp),
        "res4/unpaired/peek": lambda b, g, e, i, a, kp: run_fixed(k, d["res4"], b, g, e, i, a, False, kp, peek=40),
        "res3/paired/eproc": lambda b, g, e, i, a, kp: run_eproc(k, d["res3"], b, g, e, i, a, kp),
        "res4/paired/eproc": lambda b, g, e, i, a, kp: run_eproc(k, d["res4"], b, g, e, i, a, kp),
        "res4/mirror/fixed": lambda b, g, e, i, a, kp: run_mirror(k, d["res4"], b, g, e, i, a, kp, False),
        "res4/mirror/eproc": lambda b, g, e, i, a, kp: run_mirror(k, d["res4"], b, g, e, i, a, kp, True),
        "res3/mirror/eproc": lambda b, g, e, i, a, kp: run_mirror(k, d["res3"], b, g, e, i, a, kp, True),
    }


def cell(k, effect, inter, kappa, budget, reps):
    active = (0, 1)
    inert = tuple(range(2, k))
    ac3 = alias_col(designs(k)["res3"], k)
    out = {}
    for name, fn in arms(k).items():
        acc = {"rec": 0, "fwer": 0, "alias": 0, "calls": 0, "est_alias": 0.0, "early": 0}
        for rep in range(reps):
            rng = random.Random(hash((name, k, effect, inter, kappa, budget, rep)) & 0xFFFFFFFF)
            r = fn(budget, rng, effect, inter, active, kappa)
            adm = set(r["admitted"])
            acc["rec"] += len(adm & set(active))
            acc["fwer"] += 1 if adm & set(inert) else 0
            if ac3 is not None and ac3 in inert:
                acc["alias"] += 1 if ac3 in adm else 0
                acc["est_alias"] += r["est"][ac3]
            acc["calls"] += r["calls"]
            acc["early"] += 1 if r["early"] else 0
        n_rec = reps * len(active)
        p_rec = acc["rec"] / n_rec
        p_fw = acc["fwer"] / reps
        out[name] = {
            "recovery_pct": round(100 * p_rec, 1),
            "recovery_se": round(100 * math.sqrt(max(p_rec, 1e-9) * (1 - p_rec) / n_rec), 1),
            "fwer_pct": round(100 * p_fw, 1),
            "fwer_se": round(100 * math.sqrt(max(p_fw, 1e-9) * (1 - p_fw) / reps), 1),
            "alias_admit_pct": round(100 * acc["alias"] / reps, 1),
            "est_alias_col": round(acc["est_alias"] / reps, 4),
            "calls_avg": round(acc["calls"] / reps, 1),
            "early_stop_pct": round(100 * acc["early"] / reps, 1)}
    return out


def main(reps=300):
    t0 = time.time()
    res = {"params": {"churn": CHURN, "fail_share": FAIL_SHARE, "alpha": ALPHA,
                      "z_bonf": Z_BONF, "reps": reps, "designs": {}},
           "cells": {}}
    for k in (5, 10):
        d = designs(k)
        res["params"]["designs"][k] = {
            "full_rows": len(d["full"]), "res3_rows": len(d["res3"]), "res4_rows": len(d["res4"]),
            "res3_alias_of_01": alias_col(d["res3"], k),
            "res4_alias_of_01": alias_col(d["res4"], k),
            "res3_orthogonal": is_orthogonal(d["res3"]),
            "res4_orthogonal": is_orthogonal(d["res4"])}
    grid = []
    for k in (5, 10):
        for kappa, ktag in ((None, "homog"), (4.0, "hetero")):
            for label, eff, inter in (("null", 0.0, 0.0), ("main", 0.15, 0.0),
                                      ("interference", 0.15, -0.12), ("synergy", 0.15, 0.12)):
                grid.append((k, label, eff, inter, kappa, ktag))
    for k, label, eff, inter, kappa, ktag in grid:
        for b in (400, 1600, 6400):
            key = "k%d|%s|%s|%d" % (k, label, ktag, b)
            res["cells"][key] = cell(k, eff, inter, kappa, b, reps)
            print("%-32s %6.1fs" % (key, time.time() - t0), flush=True)
    (_HERE / "exp_screen.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print("")
    print(json.dumps(res["params"]["designs"], indent=1))
    hdr = "%-26s%-22s%9s%8s%11s%10s%9s" % ("cell", "arm", "recov%", "FWER%", "aliasAdm%",
                                           "estAlias", "calls")
    print(hdr)
    print("-" * len(hdr))
    for ck, a in res["cells"].items():
        for name, v in a.items():
            print("%-26s%-22s%9s%8s%11s%10.4f%9s" % (ck, name, v["recovery_pct"], v["fwer_pct"],
                                                     v["alias_admit_pct"], v["est_alias_col"],
                                                     v["calls_avg"]))
    # Under the global null every arm that claims validity must hold near alpha; the
    # unadjusted interim arm is the counterexample the paper is about, so it is checked
    # in the opposite direction.
    for ck, a in res["cells"].items():
        if "|null|" not in ck:
            continue
        for name, v in a.items():
            if name.endswith("/peek"):
                continue
            assert v["fwer_pct"] <= 20.0, (ck, name, v)
    peek_null = [a["res4/unpaired/peek"]["fwer_pct"] for k_, a in res["cells"].items()
                 if "|null|" in k_]
    eproc_null = [a["res4/paired/eproc"]["fwer_pct"] for k_, a in res["cells"].items()
                  if "|null|" in k_]
    assert sum(peek_null) / len(peek_null) > sum(eproc_null) / len(eproc_null), (peek_null, eproc_null)
    print("")
    print("self-check ok  %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
