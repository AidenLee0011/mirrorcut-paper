# Experiment A preregistration DRAFT (MirrorCut, prospective strict-alpha no-drop protocol run) — 2026-09-02

Status: DRAFT. Not frozen. Freeze = Zenodo deposit (server UTC + DOI) before any benchmark model call. Spec source = sol P72_p2_r3.md §3; static audit = `c1_static_audit.json`.

## 1. Question and success criterion
Does the full MirrorCut protocol (screen at alpha_A = alpha_P = 0.05/3, reserved confirmation at alpha_C = 0.05/3), run prospectively with no dropped assignments on a version-pinned open-weight endpoint, admit a nontrivial harness component and pass reserved confirmation? Success = at least one admission by row 160 AND one-sided exact sign test p <= 1/60 on the reserved split.

## 2. Endpoint (one)
`databricks-qwen3-next-80b-a3b-instruct` on a dedicated Databricks serving endpoint backed by one registered model version. Recorded per request: serving version string, endpoint config digest, request/response IDs, UTC, decoding parameters. Any change of serving version aborts the lane. Any LLM user simulator must be pinned and recorded the same way. Label: version-pinned, not fully reproducible.

## 3. Components (k = 4), all deployable settings; +1 / -1 levels
| id | +1 | -1 | ground truth |
|---|---|---|---|
| C1 policy guard (expected-positive) | deterministic guard checks state-changing tool calls against the public tau2-bench policy preconditions and returns the exact unmet condition | unguarded dispatch | unit tests vs public policy + tool definitions |
| C2 schema diagnostics | JSON-schema validation with field/type/enum repair feedback | native runtime error text | published tool schemas |
| C3 tool-state canonicalization | lossless canonical serialization of tool results | native JSON | round-trip tests |
| C4 termination checklist | fixed checklist (requested entities, policy conditions, unresolved tool errors) before termination | current system context | prompt digest |
Static audit (outcome-blind, 2026-09-02): tasks with >= 1 state-changing expected action = retail 104/114 (91.2%), airline 26/50 (52.0%); threshold 20% passed for both domains. Only C1's intervention decisions are ground-truthed; its end-to-end effect is not.

## 4. Tasks and split
Domains retail + airline, fixed mixture. Task inventory = 114 retail + 50 airline IDs (tau2-bench pinned commit, recorded). Reserved confirmation split = 64 IDs (40 retail, 24 airline), disjoint from screening, selected by HMAC-SHA256 ordering keyed by the first NIST Randomness Beacon pulse after the Zenodo timestamp. Screening draws from the remaining 100 IDs under the same 40:24 ratio; task reuse across rows is unavoidable (160 rows over 100 IDs) and is declared here. Pooled confirmation is the only inferential analysis; per-domain is descriptive.

## 5. Alpha, threshold, stopping
alpha_A = alpha_P = alpha_C = 1/60. Admission/pruning threshold k/alpha_A = 240 (old audited lane: 80, crossed at row 48; optimistic planning 60 rows under log-linear growth, hard cap 160 rows). Rules: continue until first positive admission or row 160; simultaneous crossings all admitted; pruned components pinned at incumbent; no alpha recycling; at first admission freeze undecided at incumbent and end screening; confirmation only if >= 1 admission; if none by row 160, report the null screen, no post hoc configuration.

## 6. Confirmation
Incumbent vs selected configuration on all 64 reserved IDs, same task + simulator seed within pair, randomized order within pair, binary public grader, ties excluded from the sign statistic but retained; one-sided exact sign test p = P{Bin(D, 1/2) >= F}. Passing examples at 1/60: 6 of 6 favorable (0.0156); 9 of 10 (0.0107). Power note: with p+ = 0.15 / p- = 0.05 the reserve is underpowered (expected 12.8 discordances); with p+ = 0.25 / p- = 0.05 it is roughly adequate. The binding constraint is public task IDs, not cost.

## 7. No-drop protocol
Serialize task ID, levels, order, seeds, endpoint version, request digest and UTC before the first call; two transport retries with identical content; if all fail, score the assigned arm as the preregistered worst outcome; grader failure -> rerun the frozen deterministic grader, else worst score; record empty completions, transport and grader failures, retries and final scores separately; attrition recomputed by component and level at build time; every level must remain identifiable.

## 8. Budget and calendar (planning assumptions)
Episodes: expected 248 (120 screen + 128 confirm), max 456 incl. 8 infrastructure checks; assumed 100k input / 8k output tokens per episode at $0.30 / $1.20 per M -> $18; x2 for a simulator, x1.25 contingency -> **cap $50**. Calendar 7 days (2 implement + unit-test components, 1 freeze/register/split/endpoint, 1 screen, 1 confirm, 1 replay audit, 1 manuscript), 10-day reservation.

## 9. Reporting commitments
Report no admission, failed confirmation, or endpoint abort without substitution or additional unregistered components. Planned descriptive analyses: per-domain results, per-component e-process paths, attrition by level, execution-environment matrix.

## 9b. Recorded so far (2026-09-02)
- tau2-bench commit `a2c024725189` (2026-08-18); retail 114 / airline 50 task IDs.
- Endpoint probe: `databricks-qwen3-next-80b-a3b-instruct` returns `model = qwen3-next-instruct-091725` per response (dated model version string; recorded on every request as the version pin). No separate serving-version header.
- Components C1..C4 implemented in `components_a.py` (agent `expa_agent`), self-test 7 cases + schema diagnostics verified on real retail tools (missing `reason` -> 'reason: Field required').

## 10. Remaining before freeze
(a) implement C1..C4 as switch blocks in `v3/doppel_components.py` with unit tests; (b) record tau2-bench commit and grader digests; (c) create the pinned serving endpoint and record its config digest; (d) confirm posted Databricks prices; (e) Zenodo deposit of this file + machine-readable JSON; (f) derive the split from the beacon pulse.
