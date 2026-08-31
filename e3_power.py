import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "package"))
"""Controlled power demo: one MONOTONE component (step_budget) that must help, plus null
controls. Admission must fire on step_budget, nulls stay undecided. Anytime-valid, public
benchmark (tau2 retail, Anthropic lane). Demonstrates the admission process on real data.

  python e3_power.py --domain retail --rows 160 --batch 8
"""
import argparse, json, os, random, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE/"tau2-bench"/"src"))

MODEL=os.environ.get("E3_MODEL","anthropic/claude-haiku-4-5-20251001")
os.environ.setdefault("TAU2_LLM_NL_ASSERTIONS",MODEL)
os.environ.setdefault("TAU2_LLM_ENV_INTERFACE",MODEL)
from mirrorcut import MirrorScreen
import doppel_components as dc
ALPHA=0.05
if MODEL.startswith("databricks/"):
    # dbx serving rejects OpenAI message fields it does not know ("name") - strip them
    import litellm
    _orig_completion = litellm.completion
    def _completion(*args, **kw):
        msgs = kw.get("messages") or (args[1] if len(args) > 1 else None)
        if msgs:
            for m in msgs:
                if isinstance(m, dict):
                    m.pop("name", None)
                    for tc in (m.get("tool_calls") or []):
                        if isinstance(tc, dict):
                            tc.pop("name", None)
        # gpt-oss spends output budget on reasoning; guarantee room for the answer and
        # retry once on an empty (reasoning-only) completion
        if not kw.get("max_tokens") or kw.get("max_tokens", 0) < 4096:
            kw["max_tokens"] = 4096
        r = _orig_completion(*args, **kw)
        for _ in range(2):
            m = r.choices[0].message
            if (m.content and str(m.content).strip()) or getattr(m, "tool_calls", None):
                break
            r = _orig_completion(*args, **kw)
        return r
    litellm.completion = _completion
# component -> if ON, max_steps; the monotone positive control
STEPS_ON, STEPS_OFF = 50, 12
COMPONENTS = ["step_budget", "reflect", "fewshot", "cosmetic_null"]

def episode(domain, task, sw, seed):
    os.environ["DOPPEL_SWITCHES"]=json.dumps({k:sw.get(k,-1) for k in ["digest","search_hint","reflect","fewshot","strict"]})
    from tau2.data_model.simulation import TextRunConfig as TC
    from tau2.runner.batch import run_single_task
    max_steps = STEPS_ON if sw.get("step_budget",-1)>0 else STEPS_OFF
    kw=dict(domain=domain,agent="doppel_agent",llm_agent=MODEL,user="user_simulator",llm_user=MODEL,max_steps=max_steps)
    cfg=TC(**{k:v for k,v in kw.items() if k in set(TC.model_fields)})
    sim=run_single_task(cfg,task,seed=seed)
    r=sim.reward_info.reward if sim.reward_info else None
    if r is None: raise ValueError("no reward")
    return float(r)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--domain",default="retail"); ap.add_argument("--rows",type=int,default=160)
    ap.add_argument("--batch",type=int,default=8); ap.add_argument("--seed",type=int,default=20260820)
    ap.add_argument("--ledger",default=str(HERE/"e3_power_ledger.jsonl"))
    a=ap.parse_args()
    dc.register()
    from tau2.registry import registry
    tasks=registry.get_tasks_loader(a.domain)()
    rng=random.Random(a.seed)
    screen=MirrorScreen(COMPONENTS,alpha=ALPHA,seed=a.seed)
    led=Path(a.ledger); fed=0
    if led.exists():
        for line in led.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r=json.loads(line)
                if r.get("fed"):
                    # ledger stores +1/-1; feed() takes booleans (-1 is truthy -> corruption)
                    screen.feed({k:(v>0) for k,v in r["x"].items()},r["y_plus"],r["y_minus"],task_id=r["task_id"]); fed+=1
    t0=time.time(); skipped=0
    with led.open("a",encoding="utf-8") as f, ThreadPoolExecutor(max_workers=2*a.batch) as ex:
        while fed<a.rows and not screen.done:
            batch=screen.next_batch(min(a.batch,a.rows-fed)); jobs={}
            for row_id,cfg,mirror in batch:
                task=tasks[rng.randrange(len(tasks))]; seed=rng.randrange(10**9)
                sp={c:(1 if cfg[c] else -1) for c in COMPONENTS}; sm={c:(1 if mirror[c] else -1) for c in COMPONENTS}
                fp=ex.submit(episode,a.domain,task,sp,seed); fm=ex.submit(episode,a.domain,task,sm,seed)
                jobs[row_id]=(task,seed,sp,fp,fm)
            for row_id,(task,seed,sp,fp,fm) in jobs.items():
                if os.environ.get("E3_FAILZERO")=="1":
                    # amended protocol (P41.13): a failed episode scores its prespecified
                    # worst outcome 0.0 instead of dropping the pair (no attrition at all)
                    errs={}
                    try: yp=fp.result()
                    except Exception as e: yp=0.0; errs["plus"]=str(e)[:60]
                    try: ym=fm.result()
                    except Exception as e: ym=0.0; errs["minus"]=str(e)[:60]
                    if errs: skipped+=1
                    screen.observe_batch(row_id,yp,ym); fed+=1
                    f.write(json.dumps({"row_id":row_id,"fed":True,"task_id":getattr(task,"id",str(task)),
                        "x":sp,"y_plus":yp,"y_minus":ym,"seed":seed,"fail_zero":errs or None},
                        ensure_ascii=False)+"\n"); f.flush(); continue
                try: yp,ym=fp.result(),fm.result()
                except Exception as e:
                    skipped+=1; screen.abandon(row_id)
                    f.write(json.dumps({"row_id":row_id,"fed":False,"skip":str(e)[:60]})+"\n"); f.flush(); continue
                screen.observe_batch(row_id,yp,ym); fed+=1
                f.write(json.dumps({"row_id":row_id,"fed":True,"task_id":getattr(task,"id",str(task)),
                    "x":sp,"y_plus":yp,"y_minus":ym,"seed":seed},ensure_ascii=False)+"\n"); f.flush()
            v={k:val["verdict"] for k,val in screen.verdicts().items()}
            print(f"fed {fed}/{a.rows} skip {skipped} {(time.time()-t0)/60:.1f}min {v}",flush=True)
    if os.environ.get("E3_FAILZERO")=="1" and skipped>=max(1,fed//2):
        # infra-level mass failure would masquerade as clean zero outcomes - refuse
        print("FAILZERO GUARD: %d/%d rows had failures - run void, no result written"%(skipped,fed))
        sys.exit(1)
    out={"summary":screen.summary(),"verdicts":screen.verdicts(),"rows_fed":fed,"skipped":skipped,
         "components":COMPONENTS,"steps_on":STEPS_ON,"steps_off":STEPS_OFF,"domain":a.domain,"model":MODEL}
    (HERE/os.environ.get("E3_OUT","e3_power_result.json")).write_text(json.dumps(out,indent=1,default=str),encoding="utf-8")
    print("POWER SUMMARY:",json.dumps(out["summary"],default=str)[:400])
if __name__=="__main__": main()
