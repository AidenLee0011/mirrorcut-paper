# -*- coding: utf-8 -*-
"""P45 r20 lever 1+2: (A) decompose the ~20x conservatism on the 18 cond-null cells
(union bound removed -> threshold 1/alpha; clip relaxed -> lam_cap 0.9), and
(B) matched-realised-error with an INDEPENDENT calibration split (fresh seed stream
chooses alpha; recovery evaluated on the original seed stream).

  set PYTHONHASHSEED=0 && python exp_cond_decomp.py
"""
from __future__ import annotations
import json, os, random, sys, time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import exp_screen as E
from mirror import RowEProcess, ACTIVE, ADMITTED

REPS = 400


class Proc(RowEProcess):
    def __init__(self, k, alpha, lam_cap, union):
        super().__init__(k, alpha=alpha, lam_cap=lam_cap)
        self._union = union

    @property
    def threshold(self):
        return (self.k / self.alpha) if self._union else (1.0 / self.alpha)


def run_arm(k, budget, rng, effect, inter, active, kappa, alpha=0.05,
            lam_cap=0.45, union=True):
    pool = E.task_pool(rng, kappa)
    proc = Proc(k, alpha, lam_cap, union)
    calls = 0
    while calls + 2 <= budget:
        forced = {i: (1 if st == ADMITTED else -1) for i, st in enumerate(proc.state) if st != ACTIVE}
        x = [1 if rng.random() < 0.5 else -1 for _ in range(k)]
        for i, v in forced.items():
            x[i] = v
        mir = [(-v if i not in forced else v) for i, v in enumerate(x)]
        q = pool[rng.randrange(E.TASKS)]
        y_p = 1 if rng.random() < E.p_pass(q, x, effect, inter, active) else 0
        y_m = 1 if rng.random() < E.p_pass(q, mir, effect, inter, active) else 0
        calls += 2
        d = (y_p - y_m) / 2.0
        proc.observe_row([x[i] * d for i in range(k)])
        if proc.done:
            break
    return proc.admitted()


def cond_cells():
    for k in (5, 10):
        for kappa, ktag in ((None, "homog"), (4.0, "hetero"), (1.0, "xhetero")):
            for b in (400, 1600, 6400):
                yield k, kappa, ktag, b


def part_a():
    variants = {"base": dict(alpha=0.05, lam_cap=0.45, union=True),
                "no_union": dict(alpha=0.05, lam_cap=0.45, union=False),
                "clip09": dict(alpha=0.05, lam_cap=0.90, union=True)}
    inter = ("sf", -0.02, -0.02)   # cond_null: component 1 null in every reachable context
    active = (0,)
    out = {}
    t0 = time.time()
    for k, kappa, ktag, b in cond_cells():
        key = "k%d|cond_null|%s|%d" % (k, ktag, b)
        out[key] = {}
        for vn, kw in variants.items():
            probe = anynull = 0
            for rep in range(REPS):
                rng = random.Random(hash(("mirror/rademacher/eproc", k, 0.20, inter,
                                          kappa, b, rep, vn)) & 0xFFFFFFFF)
                adm = set(run_arm(k, b, rng, 0.20, inter, active, kappa, **kw))
                if 1 in adm:
                    probe += 1
                if adm - set(active):
                    anynull += 1
            out[key][vn] = {"probe_admit_pct": round(100 * probe / REPS, 2),
                            "anynull_admit_pct": round(100 * anynull / REPS, 2),
                            "count": "%d/%d" % (probe, REPS)}
        print(key, json.dumps(out[key]), "%.0fs" % (time.time() - t0), flush=True)
    worst = {vn: max(v[vn]["probe_admit_pct"] for v in out.values())
             for vn in variants}
    return {"reps": REPS, "cells": out, "worst_probe_admit_pct": worst}


def null_fwer(k, ktag_kappa, b, alpha, tag, reps=REPS):
    kappa = ktag_kappa
    bad = 0
    for rep in range(reps):
        rng = random.Random(hash(("calib" if tag == "calib" else
                                  "mirror/rademacher/eproc", k, 0.0, 0.0, kappa, b,
                                  rep) + ((tag,) if tag == "calib" else ())) & 0xFFFFFFFF)
        adm = run_arm(k, b, rng, 0.0, 0.0, (0, 1), kappa, alpha=alpha)
        if adm:
            bad += 1
    return 100.0 * bad / reps


def recovery(k, kappa, b, alpha, reps=REPS):
    rec = 0
    for rep in range(reps):
        rng = random.Random(hash(("mirror/rademacher/eproc", k, 0.15, 0.0, kappa, b,
                                  rep)) & 0xFFFFFFFF)
        adm = set(run_arm(k, b, rng, 0.15, 0.0, (0, 1), kappa, alpha=alpha))
        rec += len(adm & {0, 1})
    return 100.0 * rec / (reps * 2)


def part_b():
    grid = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45]
    out = {}
    for k, target in ((10, 2.2), (5, 3.2)):
        cal = {}
        best, bestd = None, 1e9
        for a in grid:
            f = null_fwer(k, 4.0, 6400, a, "calib")
            cal["%.2f" % a] = round(f, 2)
            # match = largest alpha whose calib null rate stays at or under the target
            if f <= target and (best is None or a > best):
                best = a
        if best is None:
            best = 0.05
        rec = recovery(k, 4.0, 6400, best)
        chk = null_fwer(k, 4.0, 6400, best, "eval")
        out["k%d" % k] = {"target_spend_null_pct": target, "calib_null_by_alpha": cal,
                          "matched_alpha": best,
                          "eval_null_fwer_pct": round(chk, 2),
                          "main_recovery_pct": round(rec, 1)}
        print("k%d" % k, json.dumps(out["k%d" % k]), flush=True)
    return {"reps": REPS, "note": "calibration seed stream disjoint from evaluation", **out}


def main():
    part = sys.argv[1] if len(sys.argv) > 1 else "all"
    if part in ("a", "all"):
        (_HERE / "exp_cond_decomp_a.json").write_text(
            json.dumps(part_a(), ensure_ascii=False, indent=1), encoding="utf-8")
        print("saved exp_cond_decomp_a.json")
    if part in ("b", "all"):
        (_HERE / "exp_cond_decomp_b.json").write_text(
            json.dumps(part_b(), ensure_ascii=False, indent=1), encoding="utf-8")
        print("saved exp_cond_decomp_b.json")
    a = _HERE / "exp_cond_decomp_a.json"
    b = _HERE / "exp_cond_decomp_b.json"
    if a.exists() and b.exists():
        res = {"A_decomp": json.loads(a.read_text(encoding="utf-8")),
               "B_indep_calib": json.loads(b.read_text(encoding="utf-8"))}
        (_HERE / "exp_cond_decomp.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print("saved exp_cond_decomp.json")


if __name__ == "__main__":
    main()
