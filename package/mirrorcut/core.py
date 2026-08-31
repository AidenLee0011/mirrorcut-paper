# -*- coding: utf-8 -*-
"""mirrorcut: decide which parts of an agent harness earn their place.

One job. You have k switches on an agent - a context policy, a tool subset, a retry rule, a
reflection step, a prompt edit someone proposed. You want to know which of them pay, you do
not want to enumerate 2^k configurations, and you want to be allowed to look at the numbers
while they arrive without invalidating them.

    from mirrorcut import MirrorScreen

    screen = MirrorScreen(components=["compress", "tools", "retry", "reflect", "memory"])
    for task in tasks:
        cfg, mirror = screen.next_pair()
        screen.observe(run(task, cfg), run(task, mirror))
        if screen.done:
            break
    print(screen.verdicts())

Each row runs the agent twice on the same task, at a configuration and at its exact mirror.
The difference cancels every even-order term of the response, so a two-factor interaction
cannot be charged to a component that does nothing, and each component gets its own
e-process, so the family-wise error rate holds at any stopping time.
"""
from __future__ import annotations

import math
import random

ACTIVE, ADMITTED, PRUNED, RETIRED, PINNED = ("active", "admitted", "pruned",
                                             "retired", "pinned")


class _Evidence:
    __slots__ = ("up", "down", "state", "n", "s", "ss", "path", "decided_at")

    def __init__(self):
        self.up = 1.0
        self.down = 1.0
        self.state = ACTIVE
        self.n = 0
        self.s = 0.0
        self.ss = 0.0
        self.path = []
        self.decided_at = None


class MirrorScreen:
    """Sequential, family-wise error controlled screening of harness components.

    components : names, in a fixed order.
    alpha      : family-wise level for admissions. Pruning is controlled separately at the
                 same level, so a reader who wants one number for both families reads 2 alpha.
    pin        : components held at a fixed level and excluded from screening.

    Two things a careful user should know, stated here rather than discovered later.

    First, the futility stop (evidence falling below `futility`) is a budget device, not an
    error guarantee: a component stopped this way is reported as retired (undecided-inactive) and carries no
    controlled error statement, unlike a component pruned by its harm process crossing the threshold.

    Second, once a component is decided its level is committed in both executions, and from
    that point every remaining component is being tested against the conditional null: does
    it help in the harness as committed so far. That is the deployable question, but it is
    not the marginal one; if a component interacts with an already-committed one, its
    conditional and marginal effects differ. To screen against the marginal null only,
    read the verdicts once and do not continue past the first decision.
    """

    def __init__(self, components, alpha=0.05, pin=None, seed=None, bet_cap=0.45,
                 stabiliser=0.10, futility=0.05, max_rows=None, max_invocations=None,
                 bet_floor=None):
        if bet_floor is not None:          # deprecated alias, pre-1.0 courtesy
            stabiliser = bet_floor
        self.names = list(components)
        self.k = len(self.names)
        if self.k == 0:
            raise ValueError("no components to screen")
        if not (0.0 < alpha < 1.0):
            raise ValueError("alpha must be in (0, 1), got %r" % (alpha,))
        if not (0.0 <= bet_cap < 1.0):
            raise ValueError("bet_cap must be in [0, 1), got %r" % (bet_cap,))
        if stabiliser <= 0:
            raise ValueError("stabiliser must be positive, got %r" % (stabiliser,))
        if not (0.0 < futility < 1.0):
            raise ValueError("futility must be in (0, 1), got %r" % (futility,))
        self.alpha = alpha
        self.threshold = self.k / alpha
        self.bet_cap = bet_cap
        self.stabiliser = stabiliser
        self.bet_floor = stabiliser       # deprecated read alias
        self.futility = futility
        self.rng = random.Random(seed)
        self.ev = [_Evidence() for _ in range(self.k)]
        self.pin = dict(pin or {})
        for name, level in self.pin.items():
            if name not in self.names:
                raise ValueError("pinned component %r is not one of %s" % (name, self.names))
            i = self.names.index(name)
            self.ev[i].state = PINNED
            self.ev[i].decided_at = None
        self.max_rows = max_rows
        self.max_invocations = max_invocations
        self.rows = 0
        self.invocations = 0
        self._pending = None
        self._pending_task = None
        self._batch = {}
        self._batch_seq = 0
        self._batch_id = 0
        self._open = {}
        self._task_counts = {}
        self._reuse_warned = False
        self.abandoned = 0

    @classmethod
    def for_rounds(cls, components, rounds, alpha=0.05, **kw):
        """One screen of a multi-round loop with alpha spent evenly across rounds: round r
        of R gets alpha/R, so one family-wise statement holds across all R rounds
        (manuscript, Section 6). Construct a fresh screen per round with this."""
        if rounds < 1:
            raise ValueError("rounds must be >= 1")
        return cls(components, alpha=alpha / rounds, **kw)

    # ---------------------------------------------------------------- draw
    def next_pair(self, task_id: object = None) -> "tuple[dict[str, bool], dict[str, bool]]":
        """Return (configuration, mirror) as dicts name -> bool. Both run on the same task;
        pass its identifier so the decision trail records which task produced each pair.
        One pair may be outstanding at a time: drawing a second pair before observing the
        first raises, because silently discarding a drawn configuration would let outcomes
        be attributed to levels that were never run."""
        if self._pending is not None:
            raise RuntimeError("previous pair not yet observed; call observe() first")
        levels = []
        for i, e in enumerate(self.ev):
            if e.state == PINNED:
                levels.append(1 if self.pin[self.names[i]] else -1)
            elif e.state == ADMITTED:
                levels.append(1)
            elif e.state in (PRUNED, RETIRED):
                levels.append(-1)
            else:
                levels.append(1 if self.rng.random() < 0.5 else -1)
        mirror = [(-v if self.ev[i].state == ACTIVE else v) for i, v in enumerate(levels)]
        self._pending = levels
        self._pending_task = task_id
        return (self._as_dict(levels), self._as_dict(mirror))

    def _as_dict(self, levels):
        return {n: (v == 1) for n, v in zip(self.names, levels)}

    # ---------------------------------------------------------- batched draws
    def next_batch(self, n: int, task_ids: "list | None" = None) -> "list[tuple[int, dict[str, bool], dict[str, bool]]]":
        """Draw n rows at once for parallel execution: returns a list of
        (row_id, config, mirror). Observe each with observe_batch(row_id, y, y_mirror),
        in any order.

        Validity: the bets of a batch are frozen at its draw time, computed from the
        rows observed so far - a coarser filtration, so each factor keeps conditional
        mean at most one under the null and the guarantee is unchanged. Batches may
        overlap (rolling workers): decisions fire whenever a batch completes, and
        evidence is order-invariant because the frozen products commute. Ledger replay:
        grouping recorded rows by their batch reproduces verdicts exactly when batches
        did not overlap; with overlap the replay is itself a valid screening of the
        same data (all guarantees intact) whose bets may differ slightly from the live
        run's - state which one you are reporting."""
        if self._pending is not None:
            raise RuntimeError("previous pair not yet observed; finish it first")
        bid = self._batch_id
        self._batch_id += 1
        self._open[bid] = n
        frozen = [(self._bet(e, 1), self._bet(e, -1)) for e in self.ev]
        out = []
        for j in range(n):
            levels = []
            for i, e in enumerate(self.ev):
                if e.state == PINNED:
                    levels.append(1 if self.pin[self.names[i]] else -1)
                elif e.state == ADMITTED:
                    levels.append(1)
                elif e.state in (PRUNED, RETIRED):
                    levels.append(-1)
                else:
                    levels.append(1 if self.rng.random() < 0.5 else -1)
            rid = self._batch_seq
            self._batch_seq += 1
            tid = task_ids[j] if task_ids else None
            self._batch[rid] = (levels, tid, frozen, bid)
            out.append((rid, self._as_dict(levels),
                        self._as_dict([(-v if self.ev[i].state == ACTIVE else v)
                                       for i, v in enumerate(levels)])))
        return out

    def observe_batch(self, row_id: int, outcome: float, mirror_outcome: float) -> None:
        """Feed one batched row by its row_id, in any order. Evidence updates commute
        (the batch's bets are frozen), so the state after the batch is identical for
        every arrival order; decisions are taken once, when the last row of the batch
        arrives. Rows observed after an intra-batch threshold crossing still count -
        the decision reads the end-of-batch evidence, which Ville's inequality covers."""
        for y in (outcome, mirror_outcome):
            if not (0.0 <= float(y) <= 1.0):
                raise ValueError("outcomes must be in [0, 1], got %r" % (y,))
        if row_id not in self._batch:
            raise KeyError("unknown or already-observed row_id %r" % (row_id,))
        levels, task_id, frozen, bid = self._batch.pop(row_id)
        d = (float(outcome) - float(mirror_outcome)) / 2.0
        self._apply_row(levels, d, task_id, invocations=2, frozen=frozen)
        self._open[bid] -= 1
        if self._open[bid] <= 0:
            del self._open[bid]
            self._decide()

    # ------------------------------------------------------------- observe
    def observe(self, outcome: float, mirror_outcome: float) -> None:
        """Outcomes must lie in [0, 1]: a pass/fail as 1/0, or a bounded score. Larger is
        better. Unbounded scores void the guarantee; rescale them first. The increment is
        clipped defensively, but clipping a routinely out-of-range score distorts the
        estimand, so the contract is the caller's."""
        for y in (outcome, mirror_outcome):
            if not (0.0 <= float(y) <= 1.0):
                raise ValueError("outcomes must be in [0, 1], got %r" % (y,))
        if self._pending is None:
            raise RuntimeError("call next_pair() before observe()")
        levels, self._pending = self._pending, None
        task_id, self._pending_task = self._pending_task, None
        d = (float(outcome) - float(mirror_outcome)) / 2.0
        self._apply_row(levels, d, task_id, invocations=2)
        self._decide()

    def _apply_row(self, levels, d, task_id, invocations, frozen=None):
        """The single evidence-update loop. No state transitions happen here - _decide()
        does those, at row boundaries for sequential runs and at batch boundaries for
        batched ones. Bets are the live plug-in unless a frozen batch snapshot is given."""
        self.rows += 1
        self.invocations += invocations
        if task_id is not None:
            c = self._task_counts.get(task_id, 0) + 1
            self._task_counts[task_id] = c
            if (not self._reuse_warned and self.rows >= 50
                    and self.rows > 3 * len(self._task_counts)):
                import warnings
                warnings.warn(
                    "tasks are being reused heavily (%d rows over %d distinct tasks); "
                    "the e-process needs fresh outcome randomness per run - at "
                    "temperature 0 with cached traces, duplicated evidence voids the "
                    "guarantee (LIMITS.md #8)"
                    % (self.rows, len(self._task_counts)))
                self._reuse_warned = True
        for i, e in enumerate(self.ev):
            if e.state != ACTIVE:
                continue
            g = max(-1.0, min(1.0, levels[i] * d))
            up, down = frozen[i] if frozen is not None else (self._bet(e, 1),
                                                             self._bet(e, -1))
            e.up *= 1.0 + up * g
            e.down *= 1.0 + down * (-g)
            e.n += 1
            e.s += g
            e.ss += g * g
            e.path.append((self.rows, e.up, e.down, task_id))

    def _decide(self):
        """State transitions, in one place. Called after each sequential row and at each
        batch boundary, so batched decisions are order-invariant by construction."""
        for e in self.ev:
            if e.state != ACTIVE:
                continue
            if e.up >= self.threshold:
                e.state, e.decided_at = ADMITTED, self.rows
            elif e.down >= self.threshold:
                e.state, e.decided_at = PRUNED, self.rows
            elif e.up <= self.futility:
                # a budget stop, not an error-controlled rejection
                e.state, e.decided_at = RETIRED, self.rows

    def _bet(self, e, sign):
        """Plug-in bet in the GRAPA family: lambda = clip(mu / (var + mu^2 + c), 0, cap)
        with running estimates from earlier rows only; c (`stabiliser`, default 0.1) damps
        the bet, and the warm-up bet before two signals exist is min(0.1, bet_cap).
        Predictable and non-negative, which Proposition 3 of the manuscript requires."""
        if e.n < 2:
            return min(0.1, self.bet_cap)
        mu = sign * e.s / e.n
        var = max(e.ss / e.n - (e.s / e.n) ** 2, 0.0)
        return max(0.0, min(self.bet_cap, mu / (var + mu * mu + self.stabiliser)))

    def _guard_feed(self):
        if self._pending is not None:
            raise RuntimeError("cannot feed while a next_pair draw is outstanding")
        if self._batch:
            raise RuntimeError("cannot feed while a batch is outstanding")

    def _levels_of(self, levels_by_name):
        missing = [n for n in self.names if n not in levels_by_name]
        if missing:
            raise ValueError("missing levels for %s" % missing)
        # Accept bool or +/-1 int. A bare truthiness test here once turned -1 into +1
        # and silently corrupted every replayed level; be explicit instead.
        out = []
        for n in self.names:
            v = levels_by_name[n]
            if v is True or v == 1:
                out.append(1)
            elif v is False or v == -1 or v == 0:
                out.append(-1)
            else:
                raise ValueError("level for %r must be bool or +/-1, got %r" % (n, v))
        return out

    def feed(self, levels_by_name: "dict[str, bool]", outcome: float, mirror_outcome: float, task_id: object = None) -> None:
        """Replay one recorded pair: the public path used by ledger resumption."""
        self._guard_feed()
        self._pending = self._levels_of(levels_by_name)
        self._pending_task = task_id
        self.observe(outcome, mirror_outcome)

    def feed_batch(self, rows):
        """Replay one recorded batch: bets are frozen once before the whole group and
        the decision is taken once at the end, exactly as observe_batch does live, so a
        ledger written by a batched run replays to identical evidence and verdicts in
        any recorded order. Each row is (levels_by_name, outcome, mirror_outcome) or
        (levels_by_name, outcome, mirror_outcome, task_id)."""
        self._guard_feed()
        frozen = [(self._bet(e, 1), self._bet(e, -1)) for e in self.ev]
        for row in rows:
            levels_by_name, y, ym = row[0], row[1], row[2]
            task_id = row[3] if len(row) > 3 else None
            for v in (y, ym):
                if not (0.0 <= float(v) <= 1.0):
                    raise ValueError("outcomes must be in [0, 1], got %r" % (v,))
            levels = self._levels_of(levels_by_name)
            d = (float(y) - float(ym)) / 2.0
            self._apply_row(levels, d, task_id, invocations=2, frozen=frozen)
        self._decide()

    def abandon(self, row_id: "int | None" = None) -> None:
        """Drop an outstanding draw without observing it: the crashed-worker escape
        hatch. With no argument, drops the pending next_pair draw; with a row_id, drops
        that batched row. The dropped levels were never observed, so the e-processes are
        untouched - but if crashes correlate with the configuration, the missingness is
        informative and the estimand quietly shifts (LIMITS.md #7): log abandon counts
        and investigate any switch that keeps crashing the agent."""
        if row_id is None:
            if self._pending is None:
                raise RuntimeError("nothing pending to abandon")
            self._pending = None
            self._pending_task = None
        else:
            if row_id not in self._batch:
                raise KeyError("unknown or already-observed row_id %r" % (row_id,))
            bid = self._batch[row_id][3]
            del self._batch[row_id]
            self._open[bid] -= 1
            if self._open[bid] <= 0:
                del self._open[bid]
                self._decide()
        self.abandoned += 1

    # -------------------------------------------------------------- report
    @property
    def budget_exhausted(self):
        return ((self.max_rows is not None and self.rows >= self.max_rows) or
                (self.max_invocations is not None
                 and self.invocations >= self.max_invocations))

    @property
    def done(self):
        """True when every component is decided, or the row/invocation budget is spent.
        summary()["stopped"] says which."""
        return all(e.state != ACTIVE for e in self.ev) or self.budget_exhausted

    def _anytime_ci(self, e, delta=0.05):
        """Anytime-valid confidence interval for the mean increment: empirical-Bernstein
        style, time-uniform (Howard et al. line), valid at every stopping time. Width
        adapts to the observed variance, so it is far tighter than the Hoeffding bound
        on low-variance switches while keeping the same coverage guarantee. Conservative
        by construction; per-switch delta (no union bound across switches - pair it
        with the verdict's own family-wise control)."""
        n = e.n
        if n < 2:
            return None
        mu = e.s / n
        var = max(e.ss / n - mu * mu, 1e-12)
        # time-uniform empirical-Bernstein radius (stitched, loose constants kept honest)
        ll = math.log(max(math.log(2 * n, 2), 1.0) ** 2 * 10.4 / delta)
        rad = math.sqrt(2 * var * ll / n) + 3.0 * ll / n
        return (mu - rad, mu + rad)

    def verdicts(self) -> "dict[str, dict]":
        out = {}
        for name, e in zip(self.names, self.ev):
            # `effect` is the mean signed increment x_i * (y - y_mirror) / 2: half the
            # on-minus-off outcome difference. `effect_pp` is the outcome-scale effect
            # in percentage points (double the half-difference), the human-facing one.
            # `effect_pp_ci95` is an anytime-valid interval on that scale: it may be
            # read at any time, including after the verdict, without spending error.
            eff = (e.s / e.n) if e.n else None
            ci = self._anytime_ci(e)
            out[name] = {"verdict": e.state, "evidence_for": round(e.up, 3),
                         "evidence_against": round(e.down, 3), "rows": e.n,
                         "decided_at_row": e.decided_at,
                         "effect": round(eff, 4) if eff is not None else None,
                         "effect_pp": round(200 * eff, 1) if eff is not None else None,
                         "effect_pp_ci95": ([round(200 * ci[0], 1), round(200 * ci[1], 1)]
                                            if ci else None)}
        return out

    def closed_test(self, side: str = "up") -> "dict[str, bool]":
        """Strong-FWER certification by exact closed testing on e-values, uniformly more
        powerful than the k/alpha e-Bonferroni threshold the loop decides on.

        Intersection e-value for a set S is the average of the members' e-values (a valid
        e-value under the intersection null, since each e_j is one). Exact closure shortcut:
        reject component j iff every subset containing j has average e-value >= 1/alpha;
        the minimising subset over S containing j is {j} plus an ascending prefix of the
        other components' e-values, so it suffices to check, for t = 0..k-1, the average of
        e_j with the t smallest other e-values. (A full-tail-only shortcut is NOT the
        closure and is anti-conservative; fixed 2026-08-25, cold_r2.) Reporting-time only;
        it never relaxes a decision the online threshold already made.
        """
        es = [(n, (e.up if side == "up" else e.down)) for n, e in zip(self.names, self.ev)]
        thr = 1.0 / self.alpha
        out = {}
        for j, ej in es:
            others = sorted(v for n, v in es if n != j)
            s, cnt, ok = ej, 1, ej >= thr
            for v in others:
                s += v
                cnt += 1
                if s / cnt < thr:
                    ok = False
                    break
            out[j] = ok
        return out

    def summary(self) -> dict:
        v = self.verdicts()
        closed = self.closed_test("up")
        bucket = lambda st: [n for n, w in v.items() if w["verdict"] == st]
        return {"admitted": bucket(ADMITTED), "pruned": bucket(PRUNED),
                "retired": bucket(RETIRED), "pinned": bucket(PINNED),
                "undecided": bucket(ACTIVE),
                "rows": self.rows, "invocations": self.invocations,
                "threshold": round(self.threshold, 2), "abandoned": self.abandoned,
                "alpha_admit": self.alpha, "alpha_prune": self.alpha,
                "alpha_total": 2 * self.alpha, "alpha": self.alpha,
                "closed_admitted": [n for n, ok in closed.items() if ok],
                "fwer_type": "strong (e-Bonferroni union bound; closed testing dominates)",
                "stopped": ("budget" if (self.budget_exhausted
                                         and any(e.state == ACTIVE for e in self.ev))
                            else "decided" if self.done else "running")}


class UnpairedScreen(MirrorScreen):
    """The one-invocation-per-row variant: no mirror, predictable running-mean centring.

    On homogeneous binary verifiers this is the better default - the mirror's second
    invocation buys nothing when tasks do not differ (manuscript, Section 6). Use
    `mirrorcut.pairing_gain` on a pilot to choose between the two; the guarantee is the same
    family-wise bound at any stopping time, from the same per-component e-processes.

        screen = UnpairedScreen(["compress", "tools", "retry"])
        for i, task in enumerate(tasks):
            cfg = screen.next_config(task_id=i)
            screen.observe(run(task, cfg))
            if screen.done:
                break

    The increment for component i is x_i (y - ybar), with ybar the mean of the outcomes
    of earlier rows only, so it is predictable and the e-process argument goes through
    unchanged. The task effect stays inside every increment as noise; that is the price
    of the single invocation, and exactly what `pairing_gain` weighs.
    """

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._ysum = 0.0

    def next_config(self, task_id=None):
        """Return one configuration dict; the levels of undecided components are drawn
        independently and uniformly, decided components sit at their committed level."""
        cfg, _mirror = super().next_pair(task_id=task_id)
        return cfg

    def next_pair(self, task_id=None):
        raise RuntimeError("UnpairedScreen runs one configuration per row; "
                           "use next_config() and observe(outcome)")

    def next_batch(self, n, task_ids=None):
        raise NotImplementedError(
            "batched draws are not yet implemented for UnpairedScreen (the inherited "
            "mirror version would silently compute half-differences); see ROADMAP.md")

    def observe_batch(self, row_id, outcome, mirror_outcome=None):
        raise NotImplementedError(
            "batched draws are not yet implemented for UnpairedScreen; see ROADMAP.md")

    def observe(self, outcome, mirror_outcome=None):
        if mirror_outcome is not None:
            raise ValueError("UnpairedScreen.observe takes a single outcome")
        y = float(outcome)
        if not (0.0 <= y <= 1.0):
            raise ValueError("outcomes must be in [0, 1], got %r" % (outcome,))
        if self._pending is None:
            raise RuntimeError("call next_config() before observe()")
        levels, self._pending = self._pending, None
        task_id, self._pending_task = self._pending_task, None
        centre = (self._ysum / self.rows) if self.rows else 0.5  # earlier rows only
        self._ysum += y
        self._apply_row(levels, y - centre, task_id, invocations=1)
        self._decide()

    def feed(self, levels_by_name, outcome, mirror_outcome=None, task_id=None):
        self._guard_feed()
        self._pending = self._levels_of(levels_by_name)
        self._pending_task = task_id
        self.observe(outcome)
