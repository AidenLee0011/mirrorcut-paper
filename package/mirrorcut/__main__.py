# -*- coding: utf-8 -*-
"""The mirrorcut CLI.

    mirrorcut demo                      the deterministic quickstart run
    mirrorcut doctor --flip 0.117 --candidates 8 --rows 320
                                        how broken adopt-if-better is on YOUR numbers
    mirrorcut plan --k 5 --effect 0.10 --cost 0.03
                                        rows / invocations / dollars to a decision
    mirrorcut report screen.jsonl [--json] [--svg out.svg]
                                        verdicts from a ledger; exit 1 if anything pruned

Exit codes for CI: 0 = nothing pruned, 1 = something pruned, 2 = bad input.
"""
from __future__ import annotations

import argparse
import json
import math
import sys


def _cmd_demo(_args):
    from .demo import main
    main()
    return 0


def _cmd_doctor(args):
    """Exact arithmetic of adopt-if-better under your replay flip rate: the probability
    that a do-nothing candidate wins a point comparison, per candidate and per round."""
    from math import comb
    flip, n, k = args.flip, args.rows, args.candidates
    # under the null both arms are Bernoulli(p) with the same p; the flip rate sets the
    # per-run noise floor. P(variant > champion) by symmetry = (1 - P(tie)) / 2.
    p = 0.5  # worst case; the tie probability shrinks (and q grows) as n grows anyway
    log_terms = [2 * (math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1))
                 + 2 * (i * math.log(p) + (n - i) * math.log(1 - p)) for i in range(n + 1)]
    m = max(log_terms)
    tie = sum(math.exp(t - m) for t in log_terms) * math.exp(m)
    q = (1 - tie) / 2
    round_fail = 1 - (1 - q) ** k
    print("adopt-if-better, %d runs per side, %d do-nothing candidates:" % (n, k))
    print("  P(one inert candidate wins its comparison) = %.3f" % q)
    print("  P(you adopt at least one per round)        = %.3f" % round_fail)
    print("  (your replay flip rate %.3f only makes the coin fairer; the arithmetic "
          "does not need it)" % flip)
    print("mirrorcut at the same budget holds the family-wise rate at alpha.")
    return 0


def _cmd_plan(args):
    from .plan import plan
    out = plan(k=args.k, effect=args.effect, alpha=args.alpha,
               n_active=args.active, cost_per_invocation=args.cost)
    print(json.dumps(out, indent=1))
    return 0


def _cmd_report(args):
    from .core import MirrorScreen
    from .runners import Ledger
    led = Ledger(args.ledger)
    rows = led.rows()
    if not rows:
        print("empty or missing ledger: %s" % args.ledger, file=sys.stderr)
        return 2
    hdr = getattr(led, "_seen_header", None)
    if hdr:            # reconstruct the exact screen the ledger was written by
        screen = MirrorScreen(hdr["names"], alpha=hdr.get("alpha", 0.05),
                              pin=hdr.get("pin") or None)
        names = list(hdr["names"])
    else:              # headerless legacy ledger: best effort, stated
        names = sorted(rows[0]["cfg"].keys())
        screen = MirrorScreen(names)
        print("note: no ledger header; assuming alpha=0.05, no pins, sorted names",
              file=sys.stderr)
    try:
        led.replay_into(screen)
    except ValueError as e:
        print("ledger/screen mismatch: %s" % e, file=sys.stderr)
        return 2
    v = screen.verdicts()
    if args.json:
        print(json.dumps({"summary": screen.summary(), "verdicts": v}, indent=1))
    else:
        w = max(len(n) for n in names)
        print("%-*s  %-10s  %10s  %10s  %10s" % (w, "switch", "verdict",
                                                 "evid. for", "against", "effect pp"))
        for n in names:
            r = v[n]
            word = "undecided" if r["verdict"] == "active" else r["verdict"]
            print("%-*s  %-10s  %10.2f  %10.2f  %10s" %
                  (w, n, word, r["evidence_for"], r["evidence_against"],
                   ("%+.1f" % r["effect_pp"]) if r["effect_pp"] is not None else "-"))
        srep = screen.summary()
        print("(admissions and prunings are separate families at alpha=%.3g each; "
              "one combined number reads %.3g)" % (srep["alpha_admit"],
                                                   srep["alpha_total"]))
    if args.svg:
        from .plot import evidence_svg
        evidence_svg(screen, args.svg)
        print("wrote %s" % args.svg)
    if args.html_live:
        import json as _json, os as _os
        from pathlib import Path as _P
        outdir = _P(args.html_live); outdir.mkdir(parents=True, exist_ok=True)
        tpl = (_P(__file__).resolve().parent / "viewer_template.html").read_text(encoding="utf-8")
        replay2 = MirrorScreen(names, alpha=screen.alpha, pin=(hdr.get("pin") or None) if hdr else None)
        data = {"names": names, "threshold": screen.threshold, "rows": []}
        for rec in rows:
            replay2.feed(rec["cfg"], rec["y"], rec["y_mirror"], task_id=rec.get("task"))
            data["rows"].append({"cfg": [1 if rec["cfg"][n] else 0 for n in names],
                                 "y": rec["y"], "ym": rec["y_mirror"],
                                 "up": [round(e.up, 3) for e in replay2.ev],
                                 "dn": [round(e.down, 3) for e in replay2.ev],
                                 "st": [e.state[0] for e in replay2.ev]})
        (outdir / "data.json").write_text(_json.dumps(data, separators=(",", ":")),
                                          encoding="utf-8")
        meta = {"dataset": "%s (LIVE tail-follow)" % args.ledger,
                "note": "polls data.json every 4s; re-run this command to refresh it",
                "live_url": "data.json", "footer": ["mirrorcut report --html-live"]}
        html = tpl.replace("/*__DATA__*/null", _json.dumps(data, separators=(",", ":")))
        html = html.replace("/*__META__*/{}", _json.dumps(meta))
        (outdir / "index.html").write_text(html, encoding="utf-8")
        print("wrote %s (index.html + data.json)" % outdir)
    if args.html:
        import json as _json
        from pathlib import Path as _P
        tpl = (_P(__file__).resolve().parent / "viewer_template.html").read_text(encoding="utf-8")
        data = {"names": names, "threshold": screen.threshold, "rows": []}
        replay = MirrorScreen(names, alpha=screen.alpha, pin=(hdr.get("pin") or None) if hdr else None)
        for rec in rows:
            replay.feed(rec["cfg"], rec["y"], rec["y_mirror"], task_id=rec.get("task"))
            data["rows"].append({"cfg": [1 if rec["cfg"][n] else 0 for n in names],
                                 "y": rec["y"], "ym": rec["y_mirror"],
                                 "up": [round(e.up, 3) for e in replay.ev],
                                 "dn": [round(e.down, 3) for e in replay.ev],
                                 "st": [e.state[0] for e in replay.ev]})
        meta = {"dataset": "%s - %d rows" % (args.ledger, len(rows)),
                "note": "drag the slider; solid = evidence for, hollow = against",
                "footer": ["generated by mirrorcut report --html"]}
        out = tpl.replace("/*__DATA__*/null", _json.dumps(data, separators=(",", ":")))
        out = out.replace("/*__META__*/{}", _json.dumps(meta))
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(out)
        print("wrote %s" % args.html)
    if args.junit:
        cases = []
        for n in names:
            r = v[n]
            body = ""
            if r["verdict"] == "pruned":
                body = ('<failure message="pruned: effect %+.1fpp, evidence against '
                        '%.1f"/>' % (r["effect_pp"] or 0, r["evidence_against"]))
            cases.append('<testcase classname="mirrorcut" name="%s">%s</testcase>'
                         % (n, body))
        xml = ('<?xml version="1.0"?><testsuite name="mirrorcut" tests="%d" '
               'failures="%d">%s</testsuite>'
               % (len(names), len(screen.summary()["pruned"]), "".join(cases)))
        with open(args.junit, "w", encoding="utf-8") as f:
            f.write(xml)
        print("wrote %s" % args.junit)
    return 1 if screen.summary()["pruned"] else 0


def _cmd_run(args):
    """Nightly-job producer: draws configs, hands each as JSON on stdin to --exec, reads
    a [0,1] score from its stdout, appends to the ledger, stops on decision or budget."""
    import subprocess
    from .core import MirrorScreen
    from .runners import Ledger
    import time as _time
    names = [n.strip() for n in args.switches.split(",") if n.strip()]
    if not names:
        print("--switches a,b,c is required", file=sys.stderr)
        return 2
    screen = MirrorScreen(names, alpha=args.alpha, max_rows=args.max_rows,
                          seed=args.seed)
    led = Ledger(args.ledger)
    led.write_header(screen)
    done = led.replay_into(screen)
    if done:
        print("resumed %d rows from %s" % (done, args.ledger))

    def execute(cfg, task_no):
        """Failure policy, stated: non-zero exit, unparsable stdout or timeout returns
        None; the row is abandoned (both sides), counted, and the run continues. If one
        configuration keeps failing, that correlation is informative - stop and read
        LIMITS.md #7 before trusting the verdicts."""
        payload = json.dumps({"task": task_no, "config": cfg})
        try:
            r = subprocess.run(args.exec_cmd, input=payload, capture_output=True,
                               text=True, shell=True, timeout=args.timeout)
            if r.returncode != 0:
                return None
            return max(0.0, min(1.0, float(r.stdout.strip().splitlines()[-1])))
        except (ValueError, IndexError, subprocess.TimeoutExpired):
            return None

    i = done
    t0 = _time.time()
    while not screen.done:
        if args.deadline and _time.time() - t0 > args.deadline * 3600:
            print("deadline reached", file=sys.stderr)
            break
        if screen.abandoned >= max(25, screen.rows):
            print("aborting: %d rows abandoned against %d observed - the exec command "
                  "is failing more than it runs; fix it before trusting anything"
                  % (screen.abandoned, screen.rows), file=sys.stderr)
            return 2
        cfg, mirror = screen.next_pair(task_id=i)
        y, ym = execute(cfg, i), execute(mirror, i)
        if y is None or ym is None:
            screen.abandon()
            print("row %d abandoned (exec failure); abandoned=%d"
                  % (i, screen.abandoned), file=sys.stderr)
        else:
            screen.observe(y, ym)
            led.append(i, cfg, y, ym)
        i += 1
    s = screen.summary()
    print(json.dumps(s))
    return 1 if s["pruned"] else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mirrorcut", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="deterministic quickstart run")
    d = sub.add_parser("doctor", help="exact false-adoption arithmetic for adopt-if-better")
    d.add_argument("--flip", type=float, default=0.117)
    d.add_argument("--candidates", type=int, default=8)
    d.add_argument("--rows", type=int, default=320)
    p = sub.add_parser("plan", help="rows / invocations / dollars to a decision")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--effect", type=float, default=0.10)
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--active", type=int, default=1)
    p.add_argument("--cost", type=float, default=None)
    r = sub.add_parser("report", help="verdict table from a ledger")
    r.add_argument("ledger")
    r.add_argument("--json", action="store_true")
    r.add_argument("--junit", default=None, help="write a JUnit XML verdict file")
    r.add_argument("--html", default=None,
                   help="write the interactive node-flow replay of the whole run")
    r.add_argument("--html-live", default=None,
                   help="write a live-following viewer directory (index.html + data.json); re-run to refresh data")
    r.add_argument("--svg", default=None)
    ru = sub.add_parser("run", help="drive a screen against an --exec command (CI producer)")
    ru.add_argument("--switches", required=True, help="comma-separated switch names")
    ru.add_argument("--exec", dest="exec_cmd", required=True,
                    help="command; gets {task, config} JSON on stdin, prints a [0,1] score")
    ru.add_argument("--ledger", default="screen.jsonl")
    ru.add_argument("--alpha", type=float, default=0.05)
    ru.add_argument("--max-rows", type=int, default=2000)
    ru.add_argument("--timeout", type=int, default=600)
    ru.add_argument("--seed", type=int, default=None)
    ru.add_argument("--deadline", type=float, default=None,
                    help="wall-clock budget in hours")
    args = ap.parse_args(argv)
    return {"demo": _cmd_demo, "doctor": _cmd_doctor, "plan": _cmd_plan,
            "report": _cmd_report, "run": _cmd_run}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
