# -*- coding: utf-8 -*-
"""Experiment A driver (PREREG_A.md): strict-alpha, no-drop MirrorCut screen + reserved confirmation on one pinned endpoint.

  python -X utf8 run_expA.py split      # derive reserved 64 IDs from the beacon pulse recorded in prereg_frozen.json
  python -X utf8 run_expA.py screen     # screen until first admission or row cap (alpha_A = 0.05/3, threshold 240)
  python -X utf8 run_expA.py confirm    # incumbent vs selected configuration on the 64 reserved IDs, exact sign test at 1/60
Refuses to run screen/confirm unless prereg_frozen.json exists (deposit record + beacon pulse + split hash).
"""
from __future__ import annotations
import argparse, hashlib, hmac, json, os, random, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
V3 = HERE.parent / "v3"
sys.path.insert(0, str(V3)); sys.path.insert(0, str(V3 / "tau2-bench" / "src"))
sys.path.insert(0, str(HERE.parents[3])); sys.path.insert(0, str(HERE.parents[3] / "da_backend" / "oss" / "doppel"))

MODEL = os.environ.get("EXPA_MODEL", "databricks/databricks-qwen3-next-80b-a3b-instruct")
ALPHA = 0.05 / 3            # alpha_A = alpha_P = alpha_C
ROW_CAP = 160
RESERVE = {"retail": 40, "airline": 24}
COMPONENTS = ["c1_guard", "c2_schema", "c3_canon", "c4_checklist"]
LEDGER = HERE / "expA_ledger.jsonl"
CONF_LEDGER = HERE / "expA_confirm_ledger.jsonl"
FROZEN = HERE / "prereg_frozen.json"
MODEL_LOG = HERE / "expA_model_versions.jsonl"


def _pin_model_field():
    """record the provider's returned model string on every completion (version pin evidence)."""
    import litellm
    orig = litellm.completion

    def wrapped(*a, **kw):
        msgs = kw.get("messages") or (a[1] if len(a) > 1 else None)
        if msgs:
            for m in msgs:
                if isinstance(m, dict):
                    m.pop("name", None)
        if not kw.get("max_tokens") or kw.get("max_tokens", 0) < 4096:
            kw["max_tokens"] = 4096
        r = orig(*a, **kw)
        with MODEL_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%FT%TZ", time.gmtime()), "model": getattr(r, "model", None),
                                "id": getattr(r, "id", None)}) + "\n")
        return r
    litellm.completion = wrapped


def serialized_config(sw):
    return json.dumps({k: int(sw.get(k, -1)) for k in COMPONENTS}, sort_keys=True)


def episode(domain, task, sw, seed, max_steps=30):
    os.environ["EXPA_SWITCHES"] = serialized_config(sw)
    from tau2.data_model.simulation import TextRunConfig as TC
    from tau2.runner.batch import run_single_task
    kw = dict(domain=domain, agent="expa_agent", llm_agent=MODEL, user="user_simulator", llm_user=MODEL, max_steps=max_steps)
    cfg = TC(**{k: v for k, v in kw.items() if k in set(TC.model_fields)})
    sim = run_single_task(cfg, task, seed=seed)
    r = sim.reward_info.reward if sim.reward_info else None
    if r is None:
        raise ValueError("no reward")
    return float(r)


def task_ids(domain):
    from tau2.registry import registry
    return {t.id: t for t in registry.get_tasks_loader(domain)()}


def derive_split(pulse_hex):
    """HMAC-SHA256(pulse, task_id) ordering; first RESERVE[domain] per domain are reserved."""
    out = {}
    for dom, n in RESERVE.items():
        ids = sorted(task_ids(dom))
        key = bytes.fromhex(pulse_hex)
        ranked = sorted(ids, key=lambda i: hmac.new(key, i.encode(), hashlib.sha256).hexdigest())
        out[dom] = {"reserved": ranked[:n], "screening": ranked[n:]}
    return out


def cmd_split(a):
    fz = json.loads(FROZEN.read_text(encoding="utf-8"))
    split = derive_split(fz["beacon_pulse_output"])
    (HERE / "expA_split.json").write_text(json.dumps(split, indent=1), encoding="utf-8")
    h = hashlib.sha256(json.dumps(split, sort_keys=True).encode()).hexdigest()
    print("split written; sha256", h, "| reserved", {d: len(v["reserved"]) for d, v in split.items()})


def _require_frozen():
    if not FROZEN.exists():
        sys.exit("REFUSE: prereg_frozen.json missing (deposit record + beacon pulse). Preregister first.")
    fz = json.loads(FROZEN.read_text(encoding="utf-8"))
    for k in ("deposit_url", "deposit_utc", "beacon_pulse_output", "beacon_pulse_time", "prereg_sha256"):
        if not fz.get(k):
            sys.exit("REFUSE: prereg_frozen.json lacks %s" % k)
    return fz


def cmd_screen(a):
    fz = _require_frozen(); _pin_model_field()
    import components_a as ca; ca.register()
    from mirrorcut import MirrorScreen
    split = json.loads((HERE / "expA_split.json").read_text(encoding="utf-8"))
    pools = {d: [task_ids(d)[i] for i in split[d]["screening"]] for d in RESERVE}
    rng = random.Random(int(fz["beacon_pulse_output"][:8], 16))
    screen = MirrorScreen(COMPONENTS, alpha=ALPHA, seed=rng.randrange(10**9))
    assert abs(screen.threshold - 240) < 1e-9, screen.threshold
    fed = 0
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("fed"):
                screen.feed({k: (v > 0) for k, v in r["x"].items()}, r["y_plus"], r["y_minus"], task_id=r["task_id"]); fed += 1
    t0 = time.time()
    with LEDGER.open("a", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=2 * a.batch) as ex:
        while fed < ROW_CAP and not screen.done:
            batch = screen.next_batch(min(a.batch, ROW_CAP - fed)); jobs = {}
            for row_id, cfg, mirror in batch:
                dom = "retail" if rng.random() < 40 / 64 else "airline"      # fixed 40:24 mixture
                task = pools[dom][rng.randrange(len(pools[dom]))]; seed = rng.randrange(10**9)
                sp = {c: (1 if cfg[c] else -1) for c in COMPONENTS}; sm = {c: (1 if mirror[c] else -1) for c in COMPONENTS}
                order = "plus_first" if seed % 2 == 0 else "minus_first"
                rec = {"row_id": row_id, "domain": dom, "task_id": task.id, "seed": seed, "x": sp, "exec_order": order,
                       "exec_config_plus": serialized_config(sp), "exec_config_minus": serialized_config(sm),
                       "utc_assigned": time.strftime("%FT%TZ", time.gmtime())}
                f.write(json.dumps({"assigned": rec}) + "\n"); f.flush()          # no-drop: assignment serialized BEFORE any call
                fp = ex.submit(episode, dom, task, sp, seed); fm = ex.submit(episode, dom, task, sm, seed)
                jobs[row_id] = (rec, fp, fm)
            for row_id, (rec, fp, fm) in jobs.items():
                errs = {}
                for tag, fut in (("plus", fp), ("minus", fm)):
                    val = None
                    for attempt in range(3):                                    # 2 transport retries, identical content
                        try:
                            val = fut.result() if attempt == 0 else episode(rec["domain"], task_ids(rec["domain"])[rec["task_id"]], rec["x"] if tag == "plus" else {c: -v for c, v in rec["x"].items()}, rec["seed"])
                            break
                        except Exception as e:
                            errs[tag] = errs.get(tag, []) + [str(e)[:80]]
                    if val is None:
                        val = 0.0                                                # preregistered worst outcome, never dropped
                    rec["y_plus" if tag == "plus" else "y_minus"] = val
                screen.observe_batch(row_id, rec["y_plus"], rec["y_minus"]); fed += 1
                rec.update(fed=True, fail_worst=errs or None)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
            v = {k: val["verdict"] for k, val in screen.verdicts().items()}
            print("fed %d/%d %.1fmin %s" % (fed, ROW_CAP, (time.time() - t0) / 60, v), flush=True)
            if any(val["verdict"] == "admit" for val in screen.verdicts().values()):
                break                                                            # first admission ends screening
    out = {"summary": screen.summary(), "verdicts": screen.verdicts(), "rows_fed": fed, "alpha": ALPHA, "threshold": screen.threshold,
           "components": COMPONENTS, "model": MODEL, "prereg_sha256": fz["prereg_sha256"]}
    (HERE / "expA_screen_result.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print("SCREEN:", json.dumps(out["verdicts"], default=str)[:600])


def cmd_confirm(a):
    fz = _require_frozen(); _pin_model_field()
    import components_a as ca; ca.register()
    res = json.loads((HERE / "expA_screen_result.json").read_text(encoding="utf-8"))
    admitted = [c for c, v in res["verdicts"].items() if v["verdict"] == "admit"]
    pruned = [c for c, v in res["verdicts"].items() if v["verdict"] == "prune"]
    if not admitted:
        sys.exit("no admission: confirmation not run (registered rule 6)")
    selected = {c: (1 if c in admitted else -1) for c in COMPONENTS}       # undecided and pruned at incumbent (-1)
    incumbent = {c: -1 for c in COMPONENTS}
    split = json.loads((HERE / "expA_split.json").read_text(encoding="utf-8"))
    rng = random.Random(int(fz["beacon_pulse_output"][8:16], 16))
    wins = losses = ties = 0
    with CONF_LEDGER.open("a", encoding="utf-8") as f:
        for dom in RESERVE:
            for tid in split[dom]["reserved"]:
                task = task_ids(dom)[tid]; seed = rng.randrange(10**9)
                first, second = ((selected, "selected"), (incumbent, "incumbent")) if seed % 2 == 0 else ((incumbent, "incumbent"), (selected, "selected"))
                y = {}
                for sw, tag in (first, second):
                    val = None
                    for attempt in range(3):
                        try: val = episode(dom, task, sw, seed); break
                        except Exception as e: err = str(e)[:80]
                    y[tag] = 0.0 if val is None else val
                if y["selected"] > y["incumbent"]: wins += 1
                elif y["selected"] < y["incumbent"]: losses += 1
                else: ties += 1
                f.write(json.dumps({"domain": dom, "task_id": tid, "seed": seed, "y": y, "order": first[1] + "_first"}) + "\n"); f.flush()
    from math import comb
    D = wins + losses; p = sum(comb(D, k) for k in range(wins, D + 1)) / 2 ** D if D else 1.0
    out = {"pairs": wins + losses + ties, "wins": wins, "losses": losses, "ties": ties, "sign_test_p": p, "alpha_C": ALPHA,
           "pass": p <= ALPHA, "selected": selected, "admitted": admitted, "pruned": pruned}
    (HERE / "expA_confirm_result.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("CONFIRM:", json.dumps(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["split", "screen", "confirm"]); ap.add_argument("--batch", type=int, default=4)
    a = ap.parse_args(); {"split": cmd_split, "screen": cmd_screen, "confirm": cmd_confirm}[a.cmd](a)
