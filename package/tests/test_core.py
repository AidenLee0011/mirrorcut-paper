# -*- coding: utf-8 -*-
"""Unit tests. Standalone: only the package is imported."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mirrorcut import MirrorScreen, ADMITTED, PRUNED, RETIRED, PINNED, ACTIVE


def world(cfg, rng, effects=None, churn=0.117, base=0.491):
    fail = 1.0 - base
    for name, gain in (effects or {}).items():
        if cfg[name]:
            fail *= 1.0 - gain
    p = (1.0 - churn) * (1.0 - fail) + churn / 2.0
    return 1 if rng.random() < p else 0


def drive(screen, rng, effects=None, budget=4000):
    while screen.invocations + 2 <= budget and not screen.done:
        cfg, mir = screen.next_pair()
        screen.observe(world(cfg, rng, effects), world(mir, rng, effects))
    return screen


def test_mirror_is_exact_mirror_on_undecided():
    s = MirrorScreen(["a", "b", "c"], seed=1)
    cfg, mir = s.next_pair()
    for n in s.names:
        assert cfg[n] != mir[n]


def test_pinned_never_flips_and_is_reported():
    s = MirrorScreen(["a", "b", "c"], seed=2, pin={"c": True})
    for _ in range(10):
        cfg, mir = s.next_pair()
        assert cfg["c"] is True and mir["c"] is True
        s.observe(1, 0)
    assert s.verdicts()["c"]["verdict"] == PINNED
    assert s.summary()["pinned"] == ["c"]


def test_outcome_bounds_enforced():
    s = MirrorScreen(["a"], seed=3)
    s.next_pair()
    try:
        s.observe(2.0, 0.0)
    except ValueError:
        return
    raise AssertionError("out-of-range outcome accepted")


def test_futility_is_retired_not_pruned():
    """Contract: a for-process at or below the floor is RETIRED, never PRUNED; ADMITTED
    always means the threshold was genuinely crossed."""
    s = MirrorScreen(["a", "b"], seed=4, futility=0.5)
    rng = random.Random(4)
    drive(s, rng, effects={}, budget=4000)
    for e in s.ev:
        if e.state == RETIRED:
            assert e.up <= s.futility
        if e.state == PRUNED:
            assert e.down >= s.threshold
        if e.state == ADMITTED:
            assert e.up >= s.threshold


def test_fwer_under_null_smoke():
    false_hits = 0
    for rep in range(40):
        s = MirrorScreen(["a", "b", "c", "d", "e"], seed=100 + rep)
        rng = random.Random(200 + rep)
        drive(s, rng, effects={}, budget=3000)
        if s.summary()["admitted"]:
            false_hits += 1
    assert false_hits <= 4, false_hits


def test_recovery_smoke():
    got = 0
    for rep in range(15):
        s = MirrorScreen(["a", "b", "c", "d", "e"], seed=300 + rep)
        rng = random.Random(400 + rep)
        drive(s, rng, effects={"a": 0.25, "b": 0.25}, budget=8000)
        adm = set(s.summary()["admitted"])
        got += len(adm & {"a", "b"})
    assert got >= 15, got


def test_ledger_roundtrip(tmp_path=None):
    import tempfile
    from mirrorcut.runners import Ledger
    d = Path(tempfile.mkdtemp())
    led = Ledger(d / "led.jsonl")
    s1 = MirrorScreen(["a", "b"], seed=7)
    rng = random.Random(7)
    for i in range(30):
        cfg, mir = s1.next_pair()
        y, ym = world(cfg, rng), world(mir, rng)
        s1.observe(y, ym)
        led.append(i, cfg, y, ym)
    s2 = MirrorScreen(["a", "b"], seed=7)
    n = led.replay_into(s2)
    assert n == 30
    assert s2.verdicts() == s1.verdicts()


def test_ledger_name_mismatch_fails_loudly():
    import tempfile
    from mirrorcut.runners import Ledger
    d = Path(tempfile.mkdtemp())
    led = Ledger(d / "led.jsonl")
    led.append(0, {"x": True}, 1, 0)
    s = MirrorScreen(["a"], seed=8)
    try:
        led.replay_into(s)
    except ValueError:
        return
    raise AssertionError("mismatched ledger silently replayed")


def test_screen_with_ledger_resume_equivalence():
    """Interrupt at 10 rows, resume with a fresh screen over the same task order: the
    resumed screen's verdicts equal a clean replay of its own ledger."""
    import tempfile
    from mirrorcut.runners import Ledger, screen_with_ledger

    tasks = list(range(24))

    def make_run():
        rng = random.Random(99)

        def run(task, cfg):
            return world(cfg, rng, effects={"a": 0.2})
        return run

    d = Path(tempfile.mkdtemp())
    led = Ledger(d / "led.jsonl")
    s1 = MirrorScreen(["a", "b"], seed=42)
    screen_with_ledger(s1, tasks, make_run(), led, budget=20)
    assert len(led.rows()) == 10
    s2 = MirrorScreen(["a", "b"], seed=42)
    screen_with_ledger(s2, tasks, make_run(), led, budget=48)
    assert len(led.rows()) == 24
    replayed = MirrorScreen(["a", "b"], seed=42)
    Ledger(d / "led.jsonl").replay_into(replayed)
    assert replayed.verdicts() == s2.verdicts()


def test_double_next_pair_raises():
    s = MirrorScreen(["a"], seed=5)
    s.next_pair()
    try:
        s.next_pair()
    except RuntimeError:
        return
    raise AssertionError("second next_pair() without observe() was allowed")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print("%d tests passed" % len(fns))


def test_ledger_header_and_truncation():
    from mirrorcut.runners import Ledger
    import tempfile, warnings
    from pathlib import Path as _P
    d = _P(tempfile.mkdtemp())
    led = Ledger(d / "led.jsonl")
    s1 = MirrorScreen(["a", "b"], seed=1)
    led.write_header(s1)
    cfg, mir = s1.next_pair(task_id=0)
    s1.observe(1, 0)
    led.append(0, cfg, 1, 0)
    # truncated final line survives resume with a warning
    with (d / "led.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"t": 1, "task": 1, "cfg"')
    s2 = MirrorScreen(["a", "b"], seed=1)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        n = Ledger(d / "led.jsonl").replay_into(s2)
    assert n == 1 and any("truncated" in str(x.message) for x in w)
    # changed configuration is refused
    s3 = MirrorScreen(["a", "b", "c"], seed=1)
    try:
        Ledger(d / "led.jsonl").replay_into(s3)
        assert False, "changed screen must be refused"
    except ValueError:
        pass


def test_batched_draws_match_guarantee_shape():
    s = MirrorScreen(["a", "b", "c"], seed=3)
    rows = s.next_batch(4, task_ids=[10, 11, 12, 13])
    assert len(rows) == 4
    rows2 = s.next_batch(1)                    # rolling: overlap is allowed (v0.4)
    s.observe_batch(rows2[0][0], 1, 0)
    # out-of-order observation is fine
    for rid, cfg, mir in reversed(rows):
        s.observe_batch(rid, 1, 0)
    assert s.rows == 5 and s.invocations == 10
    try:
        s.observe_batch(999, 1, 0)
        assert False
    except KeyError:
        pass


def test_budget_stop_and_effect_pp():
    s = MirrorScreen(["a", "b"], seed=2, max_rows=5)
    for i in range(10):
        if s.done:
            break
        cfg, mir = s.next_pair(task_id=i)
        s.observe(1, 0)
    r = s.summary()
    assert r["rows"] == 5 and r["stopped"] == "budget", r
    assert r["alpha_total"] == 2 * r["alpha_admit"]
    v = s.verdicts()["a"]
    assert v["effect_pp"] is not None and abs(v["effect_pp"]) <= 200


def test_batched_ledger_replay_is_exact():
    import tempfile
    from pathlib import Path as _P
    from mirrorcut.runners import Ledger
    d = _P(tempfile.mkdtemp())
    led = Ledger(d / "b.jsonl")
    rng = random.Random(9)
    live = MirrorScreen(["a", "b", "c"], seed=9)
    led.write_header(live)
    bno = 0
    while live.rows < 60:
        rows = live.next_batch(4)
        outs = []
        for rid, cfg, mir in rows:
            y, ym = (1 if rng.random() < 0.6 else 0), (1 if rng.random() < 0.4 else 0)
            outs.append((rid, cfg, y, ym))
        for rid, cfg, y, ym in outs:
            live.observe_batch(rid, y, ym)
            led.append(rid, cfg, y, ym, batch=bno)
        bno += 1
    replayed = MirrorScreen(["a", "b", "c"], seed=9)
    n = Ledger(d / "b.jsonl").replay_into(replayed)
    assert n == live.rows
    assert replayed.verdicts() == live.verdicts(), (replayed.verdicts(), live.verdicts())


def test_abandon_unbricks_batch_and_pending():
    s = MirrorScreen(["a", "b"], seed=4)
    rows = s.next_batch(3)
    s.abandon(rows[0][0])                      # crashed worker
    for rid, cfg, mir in rows[1:]:
        s.observe_batch(rid, 1, 0)
    assert s.rows == 2 and s.abandoned == 1
    rows2 = s.next_batch(1)                    # not bricked
    s.observe_batch(rows2[0][0], 0, 1)
    cfg, mir = s.next_pair()
    s.abandon()
    cfg, mir = s.next_pair()                   # pending cleared
    s.observe(1, 1)


def test_batch_order_invariance_across_decisions():
    """Adversarial: observe a batch in reverse order with a mid-batch threshold crossing;
    a draw-order replay must land on identical evidence and verdicts."""
    import tempfile
    from pathlib import Path as _P
    from mirrorcut.runners import Ledger

    def play(order):
        s = MirrorScreen(["a", "b"], seed=6, alpha=0.4)   # low threshold: crossings early
        recs = []
        for b in range(6):
            rows = s.next_batch(4, task_ids=list(range(b * 4, b * 4 + 4)))
            outs = [(rid, cfg, 1, 0) for rid, cfg, mir in rows]
            seq = list(outs) if order == "draw" else list(reversed(outs))
            for rid, cfg, y, ym in seq:
                s.observe_batch(rid, y, ym)
            recs += [(cfg, y, ym, rid) for rid, cfg, y, ym in outs]
        return s, recs

    fwd, recs = play("draw")
    rev, _ = play("reversed")
    assert fwd.verdicts() == rev.verdicts(), "arrival order changed the verdicts"
    # ledger replay in draw order equals the live reversed run too
    d = _P(tempfile.mkdtemp())
    led = Ledger(d / "o.jsonl")
    b = 0
    for i, (cfg, y, ym, rid) in enumerate(recs):
        led.append(rid, cfg, y, ym, batch=i // 4)
    rep = MirrorScreen(["a", "b"], seed=6, alpha=0.4)
    Ledger(d / "o.jsonl").replay_into(rep)
    assert rep.verdicts() == fwd.verdicts() == rev.verdicts()


def test_readme_demo_block_is_byte_identical():
    """The README quotes `mirrorcut demo` output and claims byte-identity; assert it."""
    import io as _io
    import contextlib
    from pathlib import Path as _P
    from mirrorcut import demo as _demo
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        _demo.main()
    printed = buf.getvalue().strip().splitlines()
    readme = (_P(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    for line in printed:
        assert line.strip() in readme, "README demo block is stale: %r" % line


def test_run_report_roundtrip_nonalphabetical(tmp_path=None):
    import json as _json
    import subprocess as _sp
    import sys as _sys
    import tempfile
    from pathlib import Path as _P
    d = _P(tempfile.mkdtemp())
    led = str(d / "s.jsonl")
    pkg = str(_P(__file__).resolve().parents[1])
    ex = _sys.executable + " -c \"import sys;sys.stdin.read();print(0.5)\""
    r1 = _sp.run([_sys.executable, "-m", "mirrorcut", "run", "--switches", "zeta,alpha",
                  "--exec", ex, "--ledger", led, "--max-rows", "3"],
                 capture_output=True, text=True, cwd=pkg)
    assert r1.returncode in (0, 1), r1.stderr[-300:]
    r2 = _sp.run([_sys.executable, "-m", "mirrorcut", "report", led, "--json"],
                 capture_output=True, text=True, cwd=pkg)
    assert r2.returncode in (0, 1), r2.stderr[-300:]
    j = _json.loads(r2.stdout)
    assert set(j["verdicts"].keys()) == {"zeta", "alpha"}


def test_rolling_batches_overlap():
    s = MirrorScreen(["a", "b"], seed=8)
    b1 = s.next_batch(3, task_ids=[1, 2, 3])
    b2 = s.next_batch(2, task_ids=[4, 5])      # overlapping draw: no barrier
    s.observe_batch(b2[0][0], 1, 0)            # interleaved arrival
    s.observe_batch(b1[0][0], 0, 1)
    s.observe_batch(b1[1][0], 1, 0)
    s.observe_batch(b2[1][0], 1, 1)            # batch 2 completes -> decision point
    s.observe_batch(b1[2][0], 0, 0)            # batch 1 completes -> decision point
    assert s.rows == 5 and s.invocations == 10
    b3 = s.next_batch(1)
    s.abandon(b3[0][0])                        # abandoning the whole batch still decides
    assert s.abandoned == 1
    r = s.summary()
    assert r["rows"] == 5 and r["stopped"] in ("running", "decided")


def test_feed_accepts_plus_minus_one_levels():
    # regression: -1 is truthy, so a bare truthiness test once mapped every -1 to +1
    # and corrupted all replayed evidence identically across components.
    from mirrorcut import MirrorScreen
    s1 = MirrorScreen(["a", "b"], alpha=0.05, seed=7)
    s2 = MirrorScreen(["a", "b"], alpha=0.05, seed=7)
    rows = [({"a": 1, "b": -1}, 1.0, 0.0), ({"a": -1, "b": 1}, 0.0, 1.0)]
    for x, y, ym in rows:
        s1.feed(x, y, ym)
        s2.feed({k: v == 1 for k, v in x.items()}, y, ym)
    v1, v2 = s1.verdicts(), s2.verdicts()
    assert v1["a"]["effect"] == v2["a"]["effect"] != v1["b"]["effect"]
    import pytest
    with pytest.raises(ValueError):
        s1.feed({"a": 2, "b": 1}, 1.0, 0.0)
