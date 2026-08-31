# Roadmap

Honest status. Nothing here is promised for a date; things move up when someone needs
them in an issue.

- **Adapters** (`mirrorcut[inspect]`, `[promptfoo]`, `[langsmith]`): wrap an existing
  eval suite's runner into `run(task, cfg)`. The core stays stdlib-only.
- **GitHub Action**: nightly screen, verdict table as a PR comment, exit codes wired.
- **Crash policy API**: today an out-of-range or crashed run is the caller's problem
  (score it 0 under your own grader contract, or drop the row and accept the stated
  missingness assumption); an explicit `on_failure=` with documented semantics is next.
- **PyPI Trusted Publishing + attestations** (the name history makes this non-optional).
- **MCP server** (`mirrorcut-mcp`): expose next_pair/observe/verdicts as tools so any
  agent client can screen itself; the report --html replay doubles as its UI.
- **Variance-adaptive confidence sequences** alongside the conservative Hoeffding ones.
