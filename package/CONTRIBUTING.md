# Contributing

Small, sharp PRs. The bar for merging is the same bar the library holds itself to:

1. No new dependencies. The package is stdlib-only on purpose.
2. Every behavioural claim in a docstring or the README must be backed by a test or a
   manuscript cell. If you change a number, change the thing that generates it.
3. Statistical changes (bets, thresholds, stopping rules) need the guarantee argument in
   the PR description: why the process stays a non-negative supermartingale under its
   null, with predictable bets.
4. `python -m pytest tests -q` green on 3.9 and 3.12 (CI runs both).

Bug reports with a seed and a ledger snippet are gold; "it feels wrong" reports are
welcome too - say what you expected.
