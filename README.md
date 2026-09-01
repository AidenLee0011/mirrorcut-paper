# MirrorCut artifacts

## Paper (download)

- Full manuscript (PDF, 32 pages): [paper/MirrorCut_preprint.pdf](paper/MirrorCut_preprint.pdf)
- Direct link: https://github.com/AidenLee0011/mirrorcut-paper/raw/main/paper/MirrorCut_preprint.pdf
- Under review at TMLR. This repository holds the pre-registration files, experiment ledgers and analysis code behind every number in the manuscript.


Artifacts for *MirrorCut: From Component Screening to a Shipping Certificate for LLM Agent Harnesses*
(NeurIPS 2026 Workshop on E-Values submission). License: CC BY 4.0 (see LICENSE).

## Table 1 (claims-to-artefact ledger) row-to-file map

| Table 1 row | Files |
|---|---|
| Fractional-design aliasing | `exp_mirror.py`, `exp_mirror.json` (synergy grid); sensitivity `exp_alias_sens.json` |
| Peeked interim FWER | `exp_screen.py`, `exp_screen.json`; fixed-sample 4,000-rep re-measurement `exp_fixed_diag.json` |
| Bonferroni spend over looks | `exp_mirror.py`, `exp_mirror.json` (spend arm) |
| Null-cell worst admission | `exp_mirror.py`, `exp_mirror.json` (cond-null cells) |
| Closed testing vs Bonferroni | `exp_closed_power.py`, `exp_closed_power.json` |
| Production pruning (screen-certified; ship retest open) | `e2_ledger.jsonl` (live ledger), `e2_retrofit.json` (reserved split 4-0), dated continuation prereg `e4_reserved_continuation_prereg.json` (2026-08-28) |
| Planted step-budget admission (3 model families) | `e3_power.py` (driver); ledgers `e3_power_ledger.jsonl` (haiku), `e3_power_oss_ledger.jsonl` (gpt-oss); `e3_power_summary.json` |
| Amended no-drop rerun (prereg, qwen3) | `e3_power_qwen_fz_ledger.jsonl`, prereg `e3_power_qwen_fz_prereg.json` (driver `e3_power.py` with `E3_FAILZERO=1`) |
| Matched realised error (independent calibration) | `exp_cond_decomp.py`, `exp_cond_decomp.json`, `exp_matched_realised.json` |
| Prospective ship certificate (planted, prereg) | `e4_ship.py`, `e4_ship_prereg.json`, `e4_ship_ledger.jsonl`, `e4_ship_result.json` |
| k-free stream (Section 6) | `exp_online.json`, `exp_online_null.json`, `exp_online_matched.json` |
| Attrition audit (product splits; worst case) | `exp_attrition.py`, `exp_attrition.json` |

Appendix B distributional counterexample: `exp_shortcut_ce.py`, `exp_shortcut_ce.json`
(exact rational arithmetic + 200,000-draw simulation).

Simulation grids fix `PYTHONHASHSEED=0`; stored cell values reproduce in distribution.
Ledger replay of bets is seed-free (determined by the data).
