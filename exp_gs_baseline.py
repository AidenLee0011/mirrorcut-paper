# -*- coding: utf-8 -*-
"""P61.5: valid sequential baselines at matched realised error (recovery-FWER frontier).

The submitted comparator for repeated looks was an unadjusted peeking arm, which reviewers
(Opus r32/r33, GPT-5.6-sol arch round g4) called a straw baseline. This script adds the
standard VALID sequential competitors on the same data-generating process, the same paired
contrast and the same call budget, sweeps each arm level, and reports recovery against the
realised null family-wise error.

Arms (only the inference rule differs; design = fold-over, pairing = paired):
  unadj : peek every 40 rows with a fixed-sample Bonferroni z (invalid, kept for reference)
  bonf  : planned-look Bonferroni over k components x L looks (valid, conservative)
  obf   : Lan-DeMets OBF alpha-spending group-sequential, boundaries by Monte Carlo (valid)
  cs    : normal-mixture confidence sequence, sub-Gaussian (Robbins), per-component alpha/k
  eb    : predictable-mixture empirical-Bernstein betting CS (Waudby-Smith and Ramdas)
  mirror: ours (paired mirror e-process)

  set PYTHONHASHSEED=0 && python exp_gs_baseline.py [reps]
  python exp_gs_baseline.py selfcheck
"""
from __future__ import annotations
import json, math, os, random, sys, time
from pathlib import Path
from statistics import NormalDist

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import exp_screen as E
import exp_cond_decomp as CD

ND = NormalDist()
LOOK_EVERY = 40
BUDGET = 6400
KAPPA = 4.0
EFFECT_MAIN = 0.15
GRID = [float(x) for x in os.environ.get("GS_GRID", "0.01,0.02,0.05,0.10,0.20,0.30,0.45").split(",")]
RULES = ["mirror", "eb", "cs", "obf", "bonf", "unadj"]
RULES_M = ["mirror", "eb_m", "cs_m", "obf_m", "gsh_m", "bonf_m"]


def obf_boundaries(n_looks, alpha, mc=20000, seed=7):
    """One-sided Lan-DeMets OBF spending; boundaries by Monte Carlo on Brownian paths.

    alpha_spent(t) = 2 (1 - Phi(z_{alpha/2} / sqrt(t))); the boundary at look l is the
    quantile that makes cumulative first-crossing mass equal alpha_spent(t_l).
    """
    za2 = ND.inv_cdf(1 - alpha / 2)
    ts = [(i + 1) / n_looks for i in range(n_looks)]
    spend = [2 * (1 - ND.cdf(za2 / math.sqrt(t))) for t in ts]
    rng = random.Random(seed)
    paths = []
    for _ in range(mc):
        s, row = 0.0, []
        for i in range(n_looks):
            s += rng.gauss(0.0, 1.0) / math.sqrt(n_looks)
            row.append(s / math.sqrt(ts[i]))
        paths.append(row)
    alive = list(range(mc))
    bounds, cum = [], 0.0
    for l in range(n_looks):
        need = max(spend[l] - cum, 0.0)
        n_cross = int(round(need * mc))
        vals = sorted((paths[p][l] for p in alive), reverse=True)
        z = 8.0 if (n_cross <= 0 or not vals) else vals[min(n_cross, len(vals)) - 1]
        bounds.append(z)
        alive = [p for p in alive if paths[p][l] < z]
        cum = 1.0 - len(alive) / mc
    return bounds


def obf_spending(n_looks, alpha):
    """Finite-sample valid group-sequential arm: OBF-SHAPED alpha increments, spent by a
    Hoeffding bound for bounded martingale differences (no Brownian/normal approximation).
    Sum of increments <= alpha, so a union bound over looks keeps the per-component level."""
    za2 = ND.inv_cdf(1 - alpha / 2)
    ts = [(i + 1) / n_looks for i in range(n_looks)]
    spend = [2 * (1 - ND.cdf(za2 / math.sqrt(t))) for t in ts]
    inc, prev = [], 0.0
    for s in spend:
        inc.append(max(s - prev, 1e-12))
        prev = s
    scale = alpha / sum(inc)
    return [v * scale for v in inc]


_OBF = {}


def obf_cached(n_looks, alpha):
    key = (n_looks, round(alpha, 5))
    if key not in _OBF:
        _OBF[key] = obf_boundaries(n_looks, alpha)
    return _OBF[key]


def run_seq(k, x, budget, rng, effect, inter, active, kappa, rule, alpha, mirrored=False):
    """Paired screening with interim analyses; the rule fixes the stopping boundary."""
    n_rows = budget // 2
    n_looks = max(n_rows // LOOK_EVERY, 1)
    m = len(x)
    pool = E.task_pool(rng, kappa)
    champ = [-1] * k
    s_ = [0.0] * k
    ss = [0.0] * k
    log_e = [0.0] * k
    mu_hat = [0.5] * k
    v_hat = [0.25] * k
    adm = set()
    a_i = alpha / k
    thr = math.log(1.0 / a_i)
    z_unadj = E.Z_BONF[k]
    z_bonf = ND.inv_cdf(1 - min(a_i / n_looks, 0.4999))
    bounds = obf_cached(n_looks, a_i) if rule == "obf" else None
    spend_inc = obf_spending(n_looks, a_i) if rule == "gsh" else None
    rho = 400.0
    bnd = 0.5 if mirrored else 1.0
    look = 0
    n = 0
    for j in range(n_rows):
        q = pool[rng.randrange(E.TASKS)]
        cfg = x[j % m]
        if mirrored:
            mirr = [-v for v in cfg]
            y_p = 1 if rng.random() < E.p_pass(q, cfg, effect, inter, active) else 0
            y_m = 1 if rng.random() < E.p_pass(q, mirr, effect, inter, active) else 0
            d = (y_p - y_m) / 2.0
        else:
            y_c = 1 if rng.random() < E.p_pass(q, champ, effect, inter, active) else 0
            y_v = 1 if rng.random() < E.p_pass(q, cfg, effect, inter, active) else 0
            d = y_v - y_c
        n = j + 1
        for i in range(k):
            g = cfg[i] * d
            s_[i] += g
            ss[i] += g * g
            if rule == "eb":
                lam = min(0.5, math.sqrt(2 * thr / max(v_hat[i] * n * math.log(n + 1), 1e-9)))
                z = (g / bnd + 1.0) / 2.0
                log_e[i] += math.log(max(1.0 + lam * (z - 0.5), 1e-12))
                nm = mu_hat[i] + (z - mu_hat[i]) / (n + 1)
                v_hat[i] += ((z - mu_hat[i]) * (z - nm) - v_hat[i]) / (n + 1)
                v_hat[i] = max(v_hat[i], 1e-4)
                mu_hat[i] = nm
        if n % LOOK_EVERY:
            continue
        look += 1
        for i in range(k):
            if i in adm:
                continue
            if rule == "eb":
                if log_e[i] >= thr:
                    adm.add(i)
                continue
            if rule == "cs":
                # sub-Gaussian proxy = the increment bound (1/2 for mirrored rows, 1 otherwise)
                b = bnd * math.sqrt((n + rho) * (2 * thr + math.log((n + rho) / rho)))
                if s_[i] >= b:
                    adm.add(i)
                continue
            mu = s_[i] / n
            var = max(ss[i] / n - mu * mu, 1e-12)
            z = mu / math.sqrt(var / n)
            if rule == "unadj" and z > z_unadj:
                adm.add(i)
            elif rule == "bonf" and z > z_bonf:
                adm.add(i)
            elif rule == "obf" and z > bounds[min(look, len(bounds)) - 1]:
                adm.add(i)
            elif rule == "gsh" and s_[i] >= bnd * math.sqrt(
                    2.0 * n * math.log(1.0 / max(spend_inc[min(look, len(spend_inc)) - 1], 1e-12))):
                adm.add(i)
        if adm:
            return {"admitted": sorted(adm), "calls": n * 2, "early": True}
    return {"admitted": sorted(adm), "calls": n_rows * 2, "early": False}


def run_mirror_alpha(k, x, budget, rng, effect, inter, active, kappa, alpha):
    """The paper's Stage-1 arm: row-level mirror e-process (exp_cond_decomp.run_arm),
    level as an argument."""
    adm = CD.run_arm(k, budget, rng, effect, inter, active, kappa, alpha=alpha)
    return {"admitted": list(adm), "calls": budget}


def arm_run(rule, k, budget, rng, effect, inter, active, kappa, alpha):
    d = E.designs(k)
    if rule == "mirror":
        return run_mirror_alpha(k, None, budget, rng, effect, inter, active, kappa, alpha)
    mirrored = rule.endswith("_m")
    return run_seq(k, d["res4"], budget, rng, effect, inter, active, kappa,
                   rule[:-2] if mirrored else rule, alpha, mirrored)


def null_fwer(rule, k, alpha, reps, stream):
    bad = 0
    for rep in range(reps):
        rng = random.Random(hash((stream, rule, k, alpha, KAPPA, BUDGET, rep)) & 0xFFFFFFFF)
        if arm_run(rule, k, BUDGET, rng, 0.0, 0.0, (0, 1), KAPPA, alpha)["admitted"]:
            bad += 1
    return 100.0 * bad / reps


def recovery(rule, k, alpha, reps):
    rec = 0
    for rep in range(reps):
        rng = random.Random(hash(("eval", rule, k, alpha, KAPPA, BUDGET, rep)) & 0xFFFFFFFF)
        r = arm_run(rule, k, BUDGET, rng, EFFECT_MAIN, 0.0, (0, 1), KAPPA, alpha)
        rec += len(set(r["admitted"]) & {0, 1})
    return 100.0 * rec / (reps * 2)


def se_pct(p_pct, n):
    p = p_pct / 100.0
    return round(100 * math.sqrt(max(p, 1e-9) * (1 - p) / n), 2)


def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    k = 10
    t0 = time.time()
    out = {"reps": reps, "k": k, "budget": BUDGET, "kappa": KAPPA, "look_every": LOOK_EVERY,
           "effect": EFFECT_MAIN, "grid": GRID, "frontier": {}, "arms": {}}
    for rule in RULES:
        pts = []
        for a in GRID:
            f = null_fwer(rule, k, a, reps, "calib")
            r = recovery(rule, k, a, reps)
            pts.append({"alpha": a, "null_pct": round(f, 2), "null_se": se_pct(f, reps),
                        "recovery_pct": round(r, 1), "rec_se": se_pct(r, 2 * reps)})
            print("  ", rule, a, "null", round(f, 2), "rec", round(r, 1),
                  "%.0fs" % (time.time() - t0), flush=True)
        out["frontier"][rule] = pts
    mp = [p for p in out["frontier"]["mirror"] if abs(p["alpha"] - 0.05) < 1e-9][0]
    target = max(mp["null_pct"], 1.0)
    out["target_realised_null_pct"] = round(target, 2)
    out["arms"]["mirror"] = {"alpha": 0.05, "null_pct": mp["null_pct"],
                             "recovery_pct": mp["recovery_pct"], "rec_se": mp["rec_se"]}
    for rule in RULES:
        if rule == "mirror":
            continue
        ok = [p for p in out["frontier"][rule] if p["null_pct"] <= target]
        best = max(ok, key=lambda p: p["alpha"]) if ok else out["frontier"][rule][0]
        chk = null_fwer(rule, k, best["alpha"], reps, "eval")
        out["arms"][rule] = {"alpha": best["alpha"], "null_pct": best["null_pct"],
                             "eval_null_pct": round(chk, 2),
                             "recovery_pct": best["recovery_pct"], "rec_se": best["rec_se"],
                             "matched": bool(ok)}
        print(rule, json.dumps(out["arms"][rule]), flush=True)
    m = out["arms"]["mirror"]["recovery_pct"]
    out["gap_vs_mirror_pp"] = {r: round(m - out["arms"][r]["recovery_pct"], 1)
                               for r in RULES if r != "mirror"}
    out["note"] = ("calibration and evaluation use disjoint seed streams; every arm receives "
                   "the same call budget and the same paired contrast; only the inference rule "
                   "differs. unadj is the invalid straw arm, kept for reference.")
    (_HERE / "exp_gs_baseline.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
    print("saved exp_gs_baseline.json", json.dumps(out["gap_vs_mirror_pp"]))


def _selfcheck():
    b = obf_boundaries(8, 0.05, mc=4000, seed=1)
    assert b[0] > b[-1] > 1.0, b
    for rule in ("bonf", "obf", "cs", "eb", "unadj"):
        r = run_seq(5, E.designs(5)["res4"], 800, random.Random(1), 0.0, 0.0, (0, 1), 4.0,
                    rule, 0.05)
        assert set(r["admitted"]) <= set(range(5)) and r["calls"] <= 800, (rule, r)
    r = run_mirror_alpha(5, None, 800, random.Random(1), 0.15, 0.0, (0, 1), 4.0, 0.05)
    assert set(r["admitted"]) <= set(range(5))
    print("selfcheck ok | obf bounds", [round(v, 2) for v in b])


def mirrored_sweep(reps=400):
    """Same increments as Stage 1 (mirrored rows); only the stopping rule differs."""
    k, t0 = 10, time.time()
    out = json.loads((_HERE / "exp_gs_baseline.json").read_text(encoding="utf-8"))
    out["frontier_mirrored"] = {}
    out["reps_mirrored"] = reps
    for rule in ("eb_m", "cs_m", "obf_m", "bonf_m"):
        pts = []
        for a in GRID:
            f = null_fwer(rule, k, a, reps, "calib")
            r = recovery(rule, k, a, reps)
            pts.append({"alpha": a, "null_pct": round(f, 2), "null_se": se_pct(f, reps),
                        "recovery_pct": round(r, 1), "rec_se": se_pct(r, 2 * reps)})
            print("  ", rule, a, "null", round(f, 2), "rec", round(r, 1),
                  "%.0fs" % (time.time() - t0), flush=True)
        out["frontier_mirrored"][rule] = pts
    tgt = out["target_realised_null_pct"]
    for rule in ("eb_m", "cs_m", "obf_m", "bonf_m"):
        ok = [p for p in out["frontier_mirrored"][rule] if p["null_pct"] <= tgt]
        best = max(ok, key=lambda p: p["alpha"]) if ok else out["frontier_mirrored"][rule][0]
        out["arms"][rule] = {"alpha": best["alpha"], "null_pct": best["null_pct"],
                             "recovery_pct": best["recovery_pct"], "rec_se": best["rec_se"],
                             "matched": bool(ok)}
        print(rule, json.dumps(out["arms"][rule]), flush=True)
    m = out["arms"]["mirror"]["recovery_pct"]
    out["gap_vs_mirror_pp_mirrored"] = {r: round(m - out["arms"][r]["recovery_pct"], 1)
                                        for r in ("eb_m", "cs_m", "obf_m", "bonf_m")}
    out["note_mirrored"] = ("the _m arms consume the SAME mirrored increments as Stage 1 "
                            "(equal budget, same design and pairing); only the stopping rule "
                            "differs, which isolates the inference axis.")
    (_HERE / "exp_gs_baseline.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
    print("saved mirrored sweep", json.dumps(out["gap_vs_mirror_pp_mirrored"]))


def confirm_null(reps=2000):
    """P62.8: high-precision null re-measurement at each arm's matched level."""
    out = json.loads((_HERE / "exp_gs_baseline.json").read_text(encoding="utf-8"))
    conf = {}
    only = os.environ.get("GS_ARMS", "").split(",") if os.environ.get("GS_ARMS") else None
    for rule, a in [(r, out["arms"][r]["alpha"]) for r in out["arms"]
                    if not only or r in only]:
        f = null_fwer(rule, out["k"], a, reps, "confirm")
        conf[rule] = {"alpha": a, "null_pct": round(f, 2), "null_se": se_pct(f, reps),
                      "reps": reps}
        print("confirm", rule, a, round(f, 2), "+-", se_pct(f, reps), flush=True)
    out.setdefault("null_confirm", {}).update(conf)
    (_HERE / "exp_gs_baseline.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
    print("saved null_confirm")


if __name__ == "__main__":
    if sys.argv[1:] and sys.argv[1] == "confirm":
        confirm_null(int(sys.argv[2]) if len(sys.argv) > 2 else 2000)
    elif sys.argv[1:] and sys.argv[1] == "mirrored":
        mirrored_sweep(int(sys.argv[2]) if len(sys.argv) > 2 else 400)
    elif sys.argv[1:] and sys.argv[1] == "selfcheck":
        _selfcheck()
    else:
        main()
