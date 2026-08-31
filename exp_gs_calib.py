# -*- coding: utf-8 -*-
"""P67.7: calibrate every sequential arm to the SAME realised family error, then confirm on
fresh replications and measure recovery there.

Protocol (fixed before running):
  A. bisect the arm level on 4,000 calibration nulls until realised family error hits 1.0%
  B. confirm the frozen level on 20,000 calibration nulls (one ratio step if off by >0.2pp)
  C. evaluate the frozen level on 50,000 FRESH null replications  -> Wilson interval
  D. measure component recovery on 5,000 alternative replications at the same frozen level

Every arm gets the identical mirrored increments, design and call budget; only the stopping
rule differs.  Arms: mirror (ours), eb_m (empirical-Bernstein betting CS), cs_m (normal
mixture CS), bonf_m (planned-look Bonferroni), obf_m (Lan-DeMets OBF, Brownian boundaries,
asymptotic), gsh_m (OBF-shaped spending with a finite-sample Hoeffding bound).

  python exp_gs_calib.py [workers] [arms,comma]
"""
from __future__ import annotations
import json, math, os, random, sys, time, zlib
from multiprocessing import Pool
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import exp_gs_baseline as G

TARGET = 1.0            # target realised family-wise error, percent
K = 10
REPS_A, REPS_B, REPS_C, REPS_D = 4000, 20000, 50000, 5000
TOL_A, TOL_B = 0.15, 0.20
ARMS = ["mirror", "eb_m", "cs_m", "bonf_m", "obf_m", "gsh_m"]
CHUNK = 250


def _seed(stream, rule, alpha, rep):
    return zlib.crc32(("%s|%s|%.6g|%d" % (stream, rule, alpha, rep)).encode()) & 0x7FFFFFFF


def _job(a):
    """(rule, alpha, stream, lo, hi, mode) -> (n, hits) ; mode 'null' or 'alt'."""
    rule, alpha, stream, lo, hi, mode = a
    hits = 0
    eff = 0.0 if mode == "null" else G.EFFECT_MAIN
    for rep in range(lo, hi):
        rng = random.Random(_seed(stream, rule, alpha, rep))
        r = G.arm_run(rule, K, G.BUDGET, rng, eff, 0.0, (0, 1), G.KAPPA, alpha)
        if mode == "null":
            hits += 1 if r["admitted"] else 0
        else:
            hits += len(set(r["admitted"]) & {0, 1})
    return (hi - lo, hits)


def measure(pool, rule, alpha, stream, reps, mode="null"):
    jobs = [(rule, alpha, stream, i, min(i + CHUNK, reps), mode)
            for i in range(0, reps, CHUNK)]
    tot = hits = 0
    for n, h in pool.imap_unordered(_job, jobs):
        tot += n
        hits += h
    den = tot if mode == "null" else 2 * tot
    return 100.0 * hits / den, hits, den


def wilson(hits, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = hits / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    hw = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (100 * max((c - hw) / d, 0.0), 100 * min((c + hw) / d, 1.0))


def calibrate(pool, rule, log):
    lo, hi = 1e-4, 0.95
    best = None
    for it in range(8):
        mid = math.sqrt(lo * hi)
        f, _, _ = measure(pool, rule, mid, "calibA", REPS_A)
        log("  bisect %-7s a=%.5f  null=%.2f%%" % (rule, mid, f))
        if best is None or abs(f - TARGET) < abs(best[1] - TARGET):
            best = (mid, f)
        if abs(f - TARGET) <= TOL_A:
            break
        if f > TARGET:
            hi = mid
        else:
            lo = mid
    alpha = best[0]
    fb, hb, nb = measure(pool, rule, alpha, "calibB", REPS_B)
    log("  confirm %-7s a=%.5f  null=%.2f%% (n=%d)" % (rule, alpha, fb, nb))
    if abs(fb - TARGET) > TOL_B and fb > 0:
        alpha2 = min(max(alpha * (TARGET / fb), 1e-5), 0.95)
        fb2, hb2, nb2 = measure(pool, rule, alpha2, "calibB", REPS_B)
        log("  restep  %-7s a=%.5f  null=%.2f%%" % (rule, alpha2, fb2))
        if abs(fb2 - TARGET) < abs(fb - TARGET):
            alpha, fb, hb, nb = alpha2, fb2, hb2, nb2
    return alpha, fb, hb, nb


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    arms = sys.argv[2].split(",") if len(sys.argv) > 2 else ARMS
    out_p = _HERE / os.environ.get("CALIB_OUT", "exp_gs_calib.json")
    out = json.loads(out_p.read_text(encoding="utf-8")) if out_p.exists() else {}
    out.update({"target_null_pct": TARGET, "k": K, "budget": G.BUDGET,
                "reps": {"calibA": REPS_A, "calibB": REPS_B, "eval_null": REPS_C,
                         "eval_alt": REPS_D},
                "effect": G.EFFECT_MAIN, "look_every": G.LOOK_EVERY,
                "note": ("levels are calibrated on calibration nulls, frozen, then measured on "
                         "disjoint fresh null and alternative streams; all arms share the same "
                         "mirrored increments, design and call budget")})
    out.setdefault("arms", {})
    t0 = time.time()

    def log(s):
        print("[%6.0fs] %s" % (time.time() - t0, s), flush=True)

    with Pool(workers) as pool:
        for rule in arms:
            log("=== %s" % rule)
            alpha, fb, hb, nb = calibrate(pool, rule, log)
            fc, hc, nc = measure(pool, rule, alpha, "evalN", REPS_C)
            lo, hi = wilson(hc, nc)
            rec, hr, nr = measure(pool, rule, alpha, "evalA", REPS_D, mode="alt")
            rlo, rhi = wilson(hr, nr)
            out["arms"][rule] = {
                "alpha": round(alpha, 6),
                "calib_null_pct": round(fb, 3), "calib_reps": nb,
                "eval_null_pct": round(fc, 3), "eval_null_ci95": [round(lo, 3), round(hi, 3)],
                "eval_null_reps": nc,
                "recovery_pct": round(rec, 2), "recovery_ci95": [round(rlo, 2), round(rhi, 2)],
                "recovery_reps": nr,
            }
            log("%-7s alpha=%.5f  eval-null %.2f%% [%.2f, %.2f]  recovery %.1f%% [%.1f, %.1f]"
                % (rule, alpha, fc, lo, hi, rec, rlo, rhi))
            out_p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    if "mirror" in out["arms"]:
        m = out["arms"]["mirror"]
        out["matched_within_pp"] = {r: round(abs(out["arms"][r]["eval_null_pct"]
                                                 - m["eval_null_pct"]), 3)
                                    for r in out["arms"] if r != "mirror"}
        out["recovery_gap_pp"] = {r: round(m["recovery_pct"] - out["arms"][r]["recovery_pct"], 2)
                                  for r in out["arms"] if r != "mirror"}
    out_p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log("saved exp_gs_calib.json")


if __name__ == "__main__":
    sys.path.insert(0, str(_HERE.parents[2]))
    from da_backend.paperops.pops import guard_local
    guard_local("exp_gs_calib: %d+%d+%d+%d reps x %d arms"
                % (REPS_A, REPS_B, REPS_C, REPS_D, len(ARMS)),
                est_minutes=110, est_calls=0)
    main()
