"""Prospective Stage-2 ship certificate on the planted control (P45 r21 fix4).

Frozen configuration c_hat = FZ screen decision (step_budget ON, all else base) frozen
at tau = FZ row 56. Reserved stream = NEW paired tau2-retail episodes collected after
tau (this run), c_hat vs c_base on the same task+seed. Single-hypothesis e-process
(threshold 1/alpha2 = 20, GRAPA bets, increments Z=(y_hat-y_base)/2 in [-1/2,1/2],
clipped bets keep 1+lam*2Z>0 via scaling by 2). Amended protocol: failed episode = 0.
Rollback rule: budget exhausted without crossing => NO certificate.

  set E3_MODEL=databricks/databricks-qwen3-next-80b-a3b-instruct
  python e4_ship.py --pairs 80
"""
import argparse, json, os, random, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE/"tau2-bench"/"src"))
sys.path.insert(0, "D:/SH_DA_Agent_202602/da_backend/oss/doppel"); sys.path.insert(0, "D:/SH_DA_Agent_202602")
MODEL = os.environ.get("E3_MODEL", "databricks/databricks-qwen3-next-80b-a3b-instruct")
os.environ.setdefault("TAU2_LLM_NL_ASSERTIONS", MODEL)
os.environ.setdefault("TAU2_LLM_ENV_INTERFACE", MODEL)
if MODEL.startswith("databricks/"):
    import litellm
    _orig = litellm.completion
    def _completion(*args, **kw):
        msgs = kw.get("messages") or (args[1] if len(args) > 1 else None)
        if msgs:
            for m in msgs:
                if isinstance(m, dict):
                    m.pop("name", None)
                    for tc in (m.get("tool_calls") or []):
                        if isinstance(tc, dict):
                            tc.pop("name", None)
        if not kw.get("max_tokens") or kw.get("max_tokens", 0) < 4096:
            kw["max_tokens"] = 4096
        r = _orig(*args, **kw)
        for _ in range(2):
            m = r.choices[0].message
            if (m.content and str(m.content).strip()) or getattr(m, "tool_calls", None):
                break
            r = _orig(*args, **kw)
        return r
    litellm.completion = _completion
import doppel_components as dc

ALPHA2 = 0.05
THRESH = 1.0 / ALPHA2
STEPS_ON, STEPS_OFF = 50, 12
C_HAT = {"step_budget": 1, "reflect": -1, "fewshot": -1, "cosmetic_null": -1}
C_BASE = {k: -1 for k in C_HAT}


def episode(domain, task, sw, seed):
    os.environ["DOPPEL_SWITCHES"] = json.dumps({k: sw.get(k, -1) for k in
        ["digest", "search_hint", "reflect", "fewshot", "strict"]})
    from tau2.data_model.simulation import TextRunConfig as TC
    from tau2.runner.batch import run_single_task
    max_steps = STEPS_ON if sw.get("step_budget", -1) > 0 else STEPS_OFF
    kw = dict(domain=domain, agent="doppel_agent", llm_agent=MODEL, user="user_simulator",
              llm_user=MODEL, max_steps=max_steps)
    cfg = TC(**{k: v for k, v in kw.items() if k in set(TC.model_fields)})
    sim = run_single_task(cfg, task, seed=seed)
    r = sim.reward_info.reward if sim.reward_info else None
    if r is None:
        raise ValueError("no reward")
    return float(r)


class ShipE:
    """Single-hypothesis e-process on Z in [-1/2, 1/2]; predictable truncated Kelly."""
    def __init__(self, lam_cap=0.45, lam_floor=0.1):
        self.e = 1.0; self.n = 0; self.s = 0.0; self.ss = 0.0
        self.cap = lam_cap; self.floor = lam_floor; self.trace = []

    def lam(self):
        if self.n < 2:
            return 0.1
        mu = self.s / self.n
        var = max(self.ss / self.n - mu * mu, 0.0)
        return max(0.0, min(self.cap, mu / (var + mu * mu + self.floor)))

    def observe(self, z):
        g = max(-0.5, min(0.5, z))
        l = self.lam()
        self.e *= 1.0 + l * 2.0 * g          # scale g to [-1,1]; 1+l*2g > 0 since l<=0.45
        self.s += 2.0 * g; self.ss += 4.0 * g * g; self.n += 1
        self.trace.append((self.n, round(self.e, 4)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="retail")
    ap.add_argument("--pairs", type=int, default=80)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20260827)
    a = ap.parse_args()
    prereg = {"alpha2": ALPHA2, "threshold": THRESH, "c_hat": C_HAT, "c_base": C_BASE,
              "tau": "FZ screen decision row 56 (e3_power_qwen_fz_result.json)",
              "budget_pairs": a.pairs, "seed": a.seed, "model": MODEL,
              "rule": "ship iff e >= 20 within budget; else rollback (no certificate)",
              "failed_episode": "scored 0 (amended protocol)",
              "registered_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    pre = HERE / "e4_ship_prereg.json"
    if not pre.exists():
        pre.write_text(json.dumps(prereg, indent=1), encoding="utf-8")
        print("prereg written", flush=True)
    dc.register()
    from tau2.registry import registry
    tasks = registry.get_tasks_loader(a.domain)()
    rng = random.Random(a.seed)
    proc = ShipE()
    led = HERE / "e4_ship_ledger.jsonl"
    fed = failz = 0
    if led.exists():
        for line in led.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                proc.observe((r["y_hat"] - r["y_base"]) / 2.0); fed += 1
        print("resumed", fed, "e=%.2f" % proc.e, flush=True)
    t0 = time.time()
    with led.open("a", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=2*a.batch) as ex:
        while fed < a.pairs and proc.e < THRESH:
            n = min(a.batch, a.pairs - fed)
            jobs = []
            for _ in range(n):
                task = tasks[rng.randrange(len(tasks))]
                seed = rng.randrange(10**9)
                fh = ex.submit(episode, a.domain, task, C_HAT, seed)
                fb = ex.submit(episode, a.domain, task, C_BASE, seed)
                jobs.append((task, seed, fh, fb))
            for task, seed, fh, fb in jobs:
                errs = {}
                try: yh = fh.result()
                except Exception as e: yh = 0.0; errs["hat"] = str(e)[:60]
                try: yb = fb.result()
                except Exception as e: yb = 0.0; errs["base"] = str(e)[:60]
                if errs: failz += 1
                proc.observe((yh - yb) / 2.0); fed += 1
                f.write(json.dumps({"pair": fed, "task_id": getattr(task, "id", str(task)),
                    "y_hat": yh, "y_base": yb, "seed": seed, "e": round(proc.e, 4),
                    "fail_zero": errs or None}, ensure_ascii=False) + "\n"); f.flush()
            print("pairs %d/%d e=%.2f fail0 %d %.1fmin" % (fed, a.pairs, proc.e, failz,
                  (time.time()-t0)/60), flush=True)
    if failz >= max(1, fed // 2):
        print("FAILZERO GUARD: %d/%d failed - run void" % (failz, fed)); sys.exit(1)
    shipped = proc.e >= THRESH
    out = {"prereg": prereg, "pairs": fed, "fail_zero_pairs": failz,
           "e_final": round(proc.e, 3), "threshold": THRESH,
           "ship_certificate": bool(shipped),
           "decided_at_pair": next((n for n, e in proc.trace if e >= THRESH), None),
           "mean_Z": round(proc.s / max(proc.n, 1) / 2.0, 4), "trace_tail": proc.trace[-5:]}
    (HERE / "e4_ship_result.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("SHIP RESULT:", json.dumps(out)[:400])


if __name__ == "__main__":
    main()
