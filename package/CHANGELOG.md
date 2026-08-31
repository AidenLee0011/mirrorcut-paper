# Changelog

## 0.4.0 (2026-08-20)
- `effect_pp_ci95` in `verdicts()`: variance-adaptive, anytime-valid confidence interval
  on the outcome scale - read it whenever you like, coverage measured at 0 violations
  over 300 simulated runs (promised <=5%).
- Rolling batches: `next_batch` no longer blocks while another batch is outstanding;
  decisions fire per completed batch, evidence stays order-invariant. Replay contract
  stated precisely in the docstring.
- Interactive replay viewer (`mirrorcut report --html`): readable pacing, per-row
  captions, discordant-row emphasis.
- `--html-live`: a tail-following live dashboard (index.html + data.json pair) that
  tracks a running screen; re-run the command to refresh, the page follows.

## 0.3.0 (2026-08-20)
- Renamed to **mirrorcut** (the old name was squatted on PyPI; a paper must not instruct
  readers to `pip install` a stranger's package).
- CLI: `mirrorcut demo | doctor | plan | report` with CI-meaningful exit codes.
- `next_batch` / `observe_batch`: parallel execution with bets frozen at draw time
  (guarantee unchanged; commitments apply between batches).
- Ledger hardening: schema header + configuration fingerprint (resume with a changed
  screen is refused), truncated-final-line tolerance.
- `plan()` budget planner; `plot.evidence_svg()`; `py.typed`.

## 0.2.0 (2026-08-19)
- `UnpairedScreen` (one invocation per row) and `pairing_gain` / `shrunk_rates` chooser.
- `MirrorScreen.for_rounds` alpha spending across proposal rounds.
- Deterministic demo, CI matrix, adoption recipes.

## 0.1.0 (2026-08-18)
- MirrorScreen, ledger resumption, calibration self-check.
