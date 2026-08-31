# -*- coding: utf-8 -*-
"""Execution adapters and the run ledger.

The screen decides; something still has to run the agent. Two things are borrowed from the
DeepSeek Harness way of working and implemented here without depending on it:

  Ledger   every observed pair is appended to a JSONL file before it reaches the screen, so
           a crashed run resumes exactly where it stopped and two screenings of the same
           ledger give the same verdicts.
The subprocess adapter for a concrete runtime lives with the experiment that uses it (the
manuscript's live run drives DeepSeek Harness through exactly this ledger), not in the
library: one function of yours, `run(task, cfg) -> outcome in [0, 1]`, is the whole contract.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path


LEDGER_SCHEMA = 1


class Ledger:
    """Append-only JSONL of observed pairs. Replaying it into a fresh screen is resumption.

    Hardening contract: single writer (there is no lock; run one screen per ledger). The
    optional first line is a header carrying the schema version and a fingerprint of the
    screen configuration, and replay_into refuses a screen whose components, alpha or
    pins differ - silently resuming a changed screen would void the guarantee. A
    truncated final line (kill -9 mid-write) is dropped with a warning rather than
    crashing the resume; that row never reached the screen, so dropping it is exact.
    Appends are fsynced. One honest nuance: a resumed run replays to identical evidence
    and verdicts, but its FUTURE draws come from a fresh RNG stream, so a crashed-and-
    resumed run is not byte-identical to a never-crashed one - it is a different, equally
    valid run of the same screen."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _fingerprint(screen):
        return {"names": list(screen.names), "alpha": screen.alpha,
                "pin": dict(screen.pin), "schema": LEDGER_SCHEMA}

    def write_header(self, screen):
        if not self.path.exists() or self.path.stat().st_size == 0:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"_header": self._fingerprint(screen)}) + "\n")

    def append(self, task_id, cfg, outcome, mirror_outcome, meta=None, batch=None):
        rec = {"t": time.time(), "task": task_id, "cfg": cfg,
               "y": outcome, "y_mirror": mirror_outcome}
        if batch is not None:
            rec["batch"] = batch
        if meta:
            rec["meta"] = meta
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def rows(self):
        if not self.path.exists():
            return []
        out = []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                if i == len(lines) - 1:
                    import warnings
                    warnings.warn("ledger %s: dropped truncated final line" % self.path)
                    continue
                raise
            if "_header" in rec:
                self._seen_header = rec["_header"]
                continue
            out.append(rec)
        return out

    def replay_into(self, screen):
        """Feed every recorded pair to a fresh screen. Returns rows replayed.

        The record must carry a level for every component the screen knows; a ledger
        written under different component names fails loudly rather than silently
        misattributing evidence."""
        self._seen_header = None
        rows = self.rows()
        hdr = getattr(self, "_seen_header", None)
        if hdr is not None:
            want = self._fingerprint(screen)
            if (hdr.get("names") != want["names"] or hdr.get("alpha") != want["alpha"]
                    or hdr.get("pin") != want["pin"]):
                raise ValueError(
                    "ledger %s was written by a different screen configuration "
                    "(components/alpha/pin changed); resuming would void the guarantee"
                    % self.path)
        n = 0
        group, group_id = [], None
        for rec in rows + [None]:                    # sentinel flushes the last group
            bid = rec.get("batch") if rec else None
            if group and (bid != group_id or bid is None):
                screen.feed_batch(group)
                n += len(group)
                group = []
            if rec is None:
                break
            if bid is None:
                screen.feed(rec["cfg"], rec["y"], rec["y_mirror"],
                            task_id=rec.get("task"))
                n += 1
            else:
                group_id = bid
                group.append((rec["cfg"], rec["y"], rec["y_mirror"], rec.get("task")))
        return n


def screen_with_ledger(screen, tasks, run, ledger, budget=None):
    """The loop most callers want: replay the ledger into the screen, then continue from
    the first unconsumed task.

    run(task, cfg_dict) -> outcome in [0, 1]. Larger is better. Tasks are consumed in
    order; on restart, the first len(ledger) tasks are treated as already screened, so
    pass the same task sequence on every run.
    """
    done = ledger.replay_into(screen)
    for i, task in enumerate(tasks[done:], start=done):
        if screen.done or (budget is not None and screen.invocations + 2 > budget):
            break
        tid = getattr(task, "id", i)
        cfg, mirror = screen.next_pair(task_id=tid)
        y = run(task, cfg)
        y_m = run(task, mirror)
        screen.observe(y, y_m)
        ledger.append(tid, cfg, y, y_m)
    return screen
