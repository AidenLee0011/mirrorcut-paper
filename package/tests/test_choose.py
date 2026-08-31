# -*- coding: utf-8 -*-
"""The pairing chooser and the unpaired screen: signs, guarantees, and API contracts."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mirrorcut import MirrorScreen, UnpairedScreen, pairing_gain  # noqa: E402


def world(rng, cfg, q, eff, active, churn=0.117):
    fail = 1.0 - q
    for a in active:
        if cfg[a]:
            fail *= 1.0 - eff
    p = (1.0 - churn) * (1.0 - fail) + churn / 2.0
    return 1.0 if rng.random() < p else 0.0


def test_chooser_signs_match_manuscript():
    # homogeneous tasks: mirror predicted to lose (manuscript ratio 0.871)
    homo = pairing_gain([0.5] * 8, effect=0.15)
    assert homo["recommend"] == "unpaired"
    assert abs(homo["ratio"] - 0.871) < 0.01
    # strong spread: mirror predicted to win
    het = pairing_gain([0.05, 0.1, 0.2, 0.9, 0.95, 0.85, 0.5, 0.15], effect=0.15)
    assert het["recommend"] == "mirror"
    assert het["ratio"] > 1.0


def test_chooser_input_contracts():
    for bad in ([], [1.2], [-0.1]):
        try:
            pairing_gain(bad)
            assert False, bad
        except ValueError:
            pass
    try:
        pairing_gain([0.5], effect=1.5)
        assert False
    except ValueError:
        pass


def test_unpaired_null_stays_nominal():
    names = ["a", "b", "c", "d", "e"]
    hits = 0
    reps = 40
    for r in range(reps):
        rng = random.Random(1000 + r)
        s = UnpairedScreen(names, seed=r)
        for i in range(3200):
            cfg = s.next_config(task_id=i)
            s.observe(world(rng, cfg, rng.betavariate(2, 2), 0.0, []))
            if s.done:
                break
        if s.summary()["admitted"]:
            hits += 1
    assert hits <= max(1, int(0.05 * reps) + 2), hits  # generous small-sample bound


def test_unpaired_recovers_live_effects():
    names = ["a", "b", "c", "d", "e"]
    rec = 0
    reps = 30
    for r in range(reps):
        rng = random.Random(2000 + r)
        s = UnpairedScreen(names, seed=r)
        for i in range(3200):
            cfg = s.next_config(task_id=i)
            s.observe(world(rng, cfg, rng.betavariate(2, 2), 0.35, ["a", "b"]))
            if s.done:
                break
        rec += len(set(s.summary()["admitted"]) & {"a", "b"})
    assert rec >= 0.9 * 2 * reps, rec


def test_unpaired_api_contracts():
    s = UnpairedScreen(["a"], seed=1)
    try:
        s.next_pair()
        assert False
    except RuntimeError:
        pass
    cfg = s.next_config()
    try:
        s.observe(0.5, 0.5)
        assert False
    except ValueError:
        pass
    s.observe(1.0)
    assert s.rows == 1 and s.invocations == 1
    # feed replays a recorded row
    s2 = UnpairedScreen(["a"], seed=1)
    s2.feed({"a": cfg["a"]}, 1.0)
    assert s2.rows == 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)


def test_for_rounds_spends_alpha():
    s = MirrorScreen.for_rounds(["a", "b"], rounds=10)
    assert abs(s.alpha - 0.005) < 1e-12
    assert s.threshold == 2 / 0.005
    try:
        MirrorScreen.for_rounds(["a"], rounds=0)
        assert False
    except ValueError:
        pass


def test_shrunk_rates_removes_binomial_noise():
    import random
    rng = random.Random(3)
    # homogeneous truth p=0.5, 3 draws per task: raw means spread ~0.083, truth 0
    outcomes = [[1 if rng.random() < 0.5 else 0 for _ in range(3)] for _ in range(60)]
    raw = [sum(v) / 3 for v in outcomes]
    from mirrorcut import shrunk_rates, pairing_gain
    shr = shrunk_rates(outcomes)
    var = lambda xs: sum((x - sum(xs) / len(xs)) ** 2 for x in xs) / len(xs)
    assert var(shr) < 0.35 * var(raw), (var(shr), var(raw))
    # corrected pilot should not fabricate heterogeneity: recommend unpaired
    assert pairing_gain(shr, effect=0.15)["recommend"] == "unpaired"
    try:
        shrunk_rates([[1]])
        assert False
    except ValueError:
        pass


def test_anytime_ci_uniform_coverage():
    """The effect CI must cover the true mean at EVERY time in >=95% of runs."""
    CHURN, BASE = 0.117, 0.491

    def world(cfg, q, rng, eff):
        fail = 1.0 - q
        if cfg["a"]:
            fail *= 1.0 - eff
        p = max(0, min(1, (1 - CHURN) * (1 - fail) + CHURN / 2))
        return 1 if rng.random() < p else 0

    viol = 0
    REP = 60
    for rep in range(REP):
        rng = random.Random(rep)
        tasks = [rng.betavariate(4 * BASE, 4 * (1 - BASE)) for _ in range(200)]
        s = MirrorScreen(["a", "b"], seed=rep)
        tm = sum(((1 - CHURN) * (1 - (1 - q) * 0.85) - (1 - CHURN) * q) / 2
                 for q in tasks) / len(tasks)
        bad = False
        for i in range(400):
            cfg, mir = s.next_pair(task_id=i)
            q = tasks[rng.randrange(200)]
            s.observe(world(cfg, q, rng, 0.15), world(mir, q, rng, 0.15))
            ci = s.verdicts()["a"]["effect_pp_ci95"]
            if ci and not (ci[0] <= 200 * tm <= ci[1]):
                bad = True
                break
            if s.done:
                break
        if bad:
            viol += 1
    assert viol <= max(1, int(0.05 * REP) + 2), viol
