# Honest limits, in full

The README carries one sentence per limit; these are the complete versions, with the
propositions they lean on (numbering refers to the manuscript in `paper/`).

1. **The estimand averages over the other switches.** The mirror contrast of switch i is
   its main effect averaged over an independent distribution of the undecided switches
   (Prop. 2). To estimate the effect against one deployed configuration, pin the rest:
   `MirrorScreen(..., pin={"tools": True})`.

2. **After the first decision the guarantee is conditional.** Once a switch is
   committed, every remaining test is against the intersection null over reachable
   committed contexts (Prop. 4): a switch that helps in no committed context is admitted
   with probability at most alpha. A switch whose effect flips sign after a commitment
   carries no guarantee - and measured, neither restart-per-epoch nor re-screening
   repairs it, because essentially every such admission happens before the first
   commitment. The remedy is verification at the final config, which is exactly what the
   live run's post-decision check does.

3. **`effect` is half the on-minus-off outcome difference.** Double it for the outcome
   scale. The confirmation run reports on the outcome scale; the two agree (-0.073 x 2
   = -0.146 vs measured -0.133, inside the CI).

4. **Mirroring can produce configurations you would never ship.** Pin the switches that
   must not move; only the flipped subset is screened.

5. **Retirement is a shipping decision without an error statement.** A futility-retired
   switch is held off in later rows. Treat `retired` as "undecided, off by budget".

6. **The estimator is old.** Antithetic variates (1956), simultaneous perturbation
   (1992), mirrored sampling, fold-over designs - the mirror difference is ancestry, not
   invention. What is new is the per-switch e-process on top, the intersection-null
   guarantee under mid-run commitments, and the measured failure account of the
   standard alternatives.

7. **Failures are your grader's contract.** Outcomes outside [0, 1] raise immediately
   rather than silently clipping your estimand. If a configuration crashes the agent,
   score it under your own grader's rules (a crash that loses the user is a 0) - do not
   drop the row, because missingness correlated with configuration breaks the null. An
   explicit `on_failure=` API is on the roadmap.

8. **Task reuse.** Rows sample tasks with replacement; outcome noise must be fresh per
   run (temperature 0 with a cached trace gives deterministic replays and the e-process
   sees duplicated evidence). If your stack caches, salt the run or drop temperature-0
   caching for screening.
