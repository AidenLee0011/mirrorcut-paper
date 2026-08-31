# Case study: the guardrail we killed

Dated 2026-08-19/20. Versions pinned here so the README doesn't go stale.

## Setup

- **Runtime**: DeepSeek Harness (`@deepseek-ai/dsh` 0.1.0-rc.7, headless profile),
  model held fixed (claude-haiku-4-5).
- **Tasks**: 358 labelled customer questions from 18 production shops, each shop with
  its own knowledge base and a deterministic, label-anchored grader: an answerable
  question must be answered with cited evidence; a question the KB cannot answer must
  be declined or escalated.
- **Switches (5, all real)**: a one-file KB index (the preview-handle context pattern of
  NVIDIA's NOOA / labs-OO-Agents 0.0.8; in our measurement the digest is ~14% of the
  full-prompt token size), a search-before-answering instruction, a mandatory self-check
  of claims against evidence, one worked example, and an evidence-strictness guardrail.

## What happened

- 450 mirrored pairs appended to a resumable ledger; 24.2% of pairs discordant.
- At row 199 the guardrail's against-process crossed the threshold (115.9 vs 100):
  **pruned as harmful**. Cost of the decision: 398 invocations, 5.0h wall clock.
- Interim state of the other four at 450 pairs: the KB index trends helpful (evidence
  3.8), the mandatory self-check trends harmful (evidence against 3.8), the worked
  example sits at its futility floor doing nothing detectable.

## The cold check

The pruning statement is the harm process's own alpha-level statement, so we verified it
with a different procedure: a fixed-sample paired comparison of the two configurations
that differ only in the guardrail (other switches at the deployment baseline), on 120
fresh task draws from the same pool, same grader.

| arm | passed |
|---|---|
| guardrail ON | 64 / 120 |
| guardrail OFF | 80 / 120 |

The same 120 tasks were run under both configurations (task-paired, which is why the
interval is tighter than an unpaired one would be): 24 discordant pairs, 4 favouring the
guardrail, 20 against it. Mean paired difference **-0.133**, 95% CI **[-0.210, -0.057]**;
exact McNemar p = 0.0015. The screen's paired effect (-0.073, half-difference scale)
doubles to -0.146 - inside the CI.

## Why a "responsible" guardrail hurts

The grader requires answerable questions to be answered with cited evidence. The strict
guardrail pushes borderline-answerable questions into refusal: it trades false answers
for false refusals, and on this task mix the refusals cost more. That is an empirical
fact about this deployment, not a claim about your guardrail - which is the point of
screening instead of arguing.
