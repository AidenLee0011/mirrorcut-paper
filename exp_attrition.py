import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "package"))
# -*- coding: utf-8 -*-
"""Attrition audit (review-2 critical fix, P41.13).

Whole-pair abandonment alone does not preserve the Rademacher law if retention
depends on the assignment. This script:
  1. replays each tau2 ledger's driver loop deterministically (MirrorScreen seed
     20260820, batch 8, rows 160) to reconstruct the assignments of ABANDONED rows
     (the live driver logged only fed rows' x); fed-row assignments are asserted
     to match the ledger exactly, which certifies the reconstruction;
  2. tests retention vs assignment independence: per component and per pairwise
     product, retention-rate split + two-sided Fisher exact p;
  3. adversarial bound: re-screens the ledger with every abandoned pair scored
     maximally AGAINST the admitted component (g_step_budget = -1/2 per abandoned
     row), a worst case over every possible unobserved outcome; if admission
     survives, no assignment-dependent attrition mechanism can have manufactured it.

  python exp_attrition.py   -> exp_attrition.json
"""
from __future__ import annotations
import json, math, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

from mirrorcut import MirrorScreen

COMPONENTS = ["step_budget", "reflect", "fewshot", "cosmetic_null"]
BATCH, ROWS, ALPHA = 8, 160, 0.05
# per-family driver seeds recovered by exact match of fed-row assignments
LEDGERS = {
    "haiku": (HERE / "v3" / "e3_power_ledger.jsonl", 20260820),
    "gpt_oss": (HERE / "v3" / "e3_power_oss_ledger.jsonl", 20260821),
    "qwen3": (HERE / "v3" / "e3_power_qwen_ledger.jsonl", 20260820),
}


def fisher_2x2(a, b, c, d):
    """Two-sided Fisher exact p for table [[a,b],[c,d]] (retained/dropped x +1/-1)."""
    def logc(n, k):
        return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    r1, r2, c1 = a + b, c + d, a + c
    n = r1 + r2
    def logp(x):
        return logc(r1, x) + logc(r2, c1 - x) - logc(n, c1)
    p_obs = logp(a)
    tot = 0.0
    for x in range(max(0, c1 - r2), min(r1, c1) + 1):
        lp = logp(x)
        if lp <= p_obs + 1e-9:
            tot += math.exp(lp)
    return min(1.0, tot)


def replay(path, seed):
    rows = {r["row_id"]: r for r in
            (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())}
    screen = MirrorScreen(COMPONENTS, alpha=ALPHA, seed=seed)
    assign, fed = {}, 0
    while fed < ROWS and not screen.done:
        active = {n for n, e in zip(COMPONENTS, screen.ev) if e.state == "active"}
        for rid, cfg, _mir in screen.next_batch(min(BATCH, ROWS - fed)):
            entry = rows.get(rid)
            assert entry is not None, ("ledger missing row", rid)
            x = {k: (1 if v else -1) for k, v in cfg.items()}
            if entry.get("fed"):
                led_x = {k: (1 if v > 0 else -1) for k, v in entry["x"].items()}
                assert led_x == x, ("assignment mismatch at row", rid, led_x, x)
                screen.observe_batch(rid, entry["y_plus"], entry["y_minus"])
                fed += 1
            else:
                screen.abandon(rid)
            assign[rid] = (x, bool(entry.get("fed")), active)
    return rows, assign


def association(assign):
    out = {}
    keys = list(COMPONENTS) + ["%s*%s" % (a, b) for i, a in enumerate(COMPONENTS)
                               for b in COMPONENTS[i + 1:]]
    for key in keys:
        def val(x):
            if "*" in key:
                a, b = key.split("*")
                return x[a] * x[b]
            return x[key]
        need = set(key.split("*")) if "*" in key else {key}
        rows_ok = [(x, f) for x, f, act in assign.values() if need <= act]
        a = sum(1 for x, f in rows_ok if f and val(x) > 0)
        b = sum(1 for x, f in rows_ok if not f and val(x) > 0)
        c = sum(1 for x, f in rows_ok if f and val(x) < 0)
        d = sum(1 for x, f in rows_ok if not f and val(x) < 0)
        out[key] = {"retained_plus": a, "dropped_plus": b, "retained_minus": c,
                    "dropped_minus": d,
                    "retain_rate_plus": round(a / max(a + b, 1), 4),
                    "retain_rate_minus": round(c / max(c + d, 1), 4),
                    "fisher_p": round(fisher_2x2(a, b, c, d), 4)}
    return out


def adversarial(rows, assign, seed, target="step_budget"):
    """Re-screen the same data via feed() in row order; abandoned pairs get the
    worst-case outcome against `target` (g_target = -1/2)."""
    screen = MirrorScreen(COMPONENTS, alpha=ALPHA, seed=seed)
    for rid in sorted(assign):
        x, fed, _act = assign[rid]
        levels = {k: (v > 0) for k, v in x.items()}
        if fed:
            screen.feed(levels, rows[rid]["y_plus"], rows[rid]["y_minus"])
        else:
            yp, ym = (0.0, 1.0) if x[target] > 0 else (1.0, 0.0)
            screen.feed(levels, yp, ym)
        if screen.done:
            break
    v = screen.verdicts()[target]
    return {"verdict": v["verdict"], "evidence_for": round(v["evidence_for"], 3),
            "decided_at_row": v.get("decided_at_row"), "rows": v.get("rows")}


def main():
    out = {"batch": BATCH, "rows_target": ROWS, "alpha": ALPHA, "families": {}}
    for fam, (path, seed) in LEDGERS.items():
        rows, assign = replay(path, seed)
        n_ab = sum(1 for _, f, _a in assign.values() if not f)
        assoc = association(assign)
        worst = max(assoc.items(), key=lambda kv: abs(kv[1]["retain_rate_plus"]
                                                      - kv[1]["retain_rate_minus"]))
        # temporal precedence: abandons occurring before the live admission decision
        decided = {"haiku": 37, "gpt_oss": 70, "qwen3": 64}[fam]  # live fed-row index
        fed_ids = [rid for rid in sorted(assign) if assign[rid][1]]
        dec_rid = fed_ids[decided - 1]
        ab_before = sum(1 for rid in sorted(assign)
                        if not assign[rid][1] and rid < dec_rid)
        out["families"][fam] = {
            "rows_drawn": len(assign), "abandoned": n_ab,
            "live_decided_fed_row": decided, "live_decided_row_id": dec_rid,
            "abandons_before_decision": ab_before,
            "reconstruction": "fed-row assignments match ledger exactly",
            "association": assoc,
            "worst_split": {"key": worst[0], **worst[1]},
            "min_fisher_p": min(v["fisher_p"] for v in assoc.values()),
            "seed": seed,
            "adversarial_step_budget": adversarial(rows, assign, seed),
        }
        f = out["families"][fam]
        print("%-8s abandoned=%d  worst split %s %.3f vs %.3f (p=%.3f)  min p=%.3f  "
              "adversarial: %s e=%.1f" % (
                  fam, n_ab, f["worst_split"]["key"], f["worst_split"]["retain_rate_plus"],
                  f["worst_split"]["retain_rate_minus"], f["worst_split"]["fisher_p"],
                  f["min_fisher_p"], f["adversarial_step_budget"]["verdict"],
                  f["adversarial_step_budget"]["evidence_for"]))
    (HERE / "exp_attrition.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("-> exp_attrition.json")


if __name__ == "__main__":
    main()
