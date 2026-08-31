# Measured results

Every number below is a cell from the manuscript's experiment grid (`paper/`), 400
replications per cell unless marked, standard errors computed at the replication level.
Zero and full cells carry one-sided 95% Clopper-Pearson bounds instead of a fake ±0.0.

## Acceptance rules for proposed edits (6400 invocations)

| acceptance rule | false adoption, k=5 null | k=10 null | k=10 live | recovery, k=10 live |
|---|---|---|---|---|
| point comparison (adopt if better) | 96.8 ± 0.9% | 100.0 (≥99.3)% | 99.2 ± 0.4% | 95.4 ± 0.7% |
| point comparison, 2pp margin | 75.8 ± 2.1% | 98.2 ± 0.7% | 95.8 ± 1.0% | 88.4 ± 1.2% |
| per-candidate z-test, no correction | 21.8 ± 2.1% | 37.5 ± 2.4% | 35.0 ± 2.4% | 54.6 ± 1.8% |
| mirror screen (this package) | 1.8 ± 0.7% | 0.8 ± 0.4% | 0.5 (≤1.6)% | 88.1 ± 1.1% |

The uncontrolled rule recovers slightly more of the good edits because it also adopts
almost everything else.

## Design baselines under interaction (6400 invocations, alias admission)

| method | recovery, k=5 | FWER, k=5 | alias admitted, k=5 | k=10 |
|---|---|---|---|---|
| full factorial, fixed sample | 100.0 (≥99.3) | 3.2 ± 0.9 | 1.2 ± 0.5% | 0.8 ± 0.4% |
| Resolution III, fixed sample | 100.0 (≥99.3) | 94.8 ± 1.1 | **94.2 ± 1.2%** | 88.2 ± 1.6% |
| fold-over (Res IV), fixed sample | 100.0 (≥99.3) | 2.8 ± 0.8 | 1.0 ± 0.5% | 0.2 (≤1.2)% |
| randomised unpaired, fixed sample | 100.0 (≥99.3) | 3.8 ± 0.9 | 1.2 ± 0.5% | 0.5 (≤1.6)% |
| mirror pairing, e-process | 100.0 (≥99.3) | 0.0 (≤0.9) | 0.0 (≤0.9)% | 0.0 (≤0.9)% |

## Peeking at a fixed-sample threshold (global null)

| looks | k=5 | k=10 |
|---|---|---|
| unadjusted interim looks every 40 rows | 29.0 ± 2.3% | **41.8 ± 2.5%** |
| alpha-spending at planned looks | 3.2 ± 0.9% | 2.2 ± 0.7% |
| e-process (this package) | 0.0 (≤0.9)% | 0.5 (≤1.6)% |

## The live run

- 450 mirrored pairs, 24.2% discordant, five real switches of a production agent.
- One decision: the evidence-strictness guardrail pruned at row 199 (against-process
  115.9 vs threshold 100), 398 invocations, 5.0h wall.
- Independent post-decision check, 120 fresh task-paired draws: on 64/120 vs off 80/120,
  mean paired difference **-0.133, 95% CI [-0.210, -0.057]**.
- Pilot chooser on the run ledger, noise-corrected: log-growth ratio 1.22
  (bootstrap 95% [1.08, 1.37]) - recommends the mirror, the arm the run used.

The complete tables (14) and figures (9), plus the review transcripts of the adversarial
rounds this package went through, are in `paper/` and the manuscript's artefact set.
