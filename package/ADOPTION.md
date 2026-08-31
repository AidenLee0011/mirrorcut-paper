# Adoption recipes

`mirrorcut` decides; your stack executes. Each recipe below is the full wiring for one common
stack: what a "component" is there, what `run()` looks like, and what the two invocations
per row cost. All recipes use the same three calls (`next_pair` / `observe` / `summary`).

## 1. Screening agent-graph options (LangGraph-style)

Components = graph-level switches you are unsure about: a reflection node, a retrieval
node, a tool-result summariser, a retry policy, a system-prompt block.

```python
from mirrorcut import MirrorScreen

switches = ["reflect_node", "retriever", "tool_summarise", "retry_on_error", "persona"]
screen = MirrorScreen(switches, seed=0)

def build_graph(cfg):
    g = base_graph()
    if cfg["reflect_node"]:   g.add_node("reflect", reflect)
    if cfg["retriever"]:      g.add_node("retrieve", retrieve)
    # ... one `if` per switch; nothing else varies
    return g.compile()

for i, task in enumerate(eval_tasks):
    cfg, mirror = screen.next_pair(task_id=i)
    screen.observe(grade(build_graph(cfg).invoke(task)),
                   grade(build_graph(mirror).invoke(task)))
    if screen.done:
        break
print(screen.summary())
```

Cost: 2 x (your per-task agent cost) per row. The k=5 manuscript cells reached decisions
inside 3,200 rows at effect sizes of a few points; strong effects decide in hundreds.

## 2. Tool-subset screening (any function-calling SDK)

Components = individual tools. `cfg` masks the tool list handed to the SDK.

```python
tools_all = {"web_search": web_search, "code_exec": code_exec,
             "calculator": calc, "file_read": file_read}
screen = MirrorScreen(list(tools_all), seed=0)
...
active = [fn for name, fn in tools_all.items() if cfg[name]]
answer = client.run(task, tools=active)
```

The mirror question this answers: which tools *earn* their context window, per your own
grader, not per intuition. Pin tools that must stay (`pin={"file_read": True}`).

## 3. Judging a prompt-edit loop (SkillOpt / GEPA-style proposers)

The proposer proposes; `mirrorcut` replaces only the acceptance rule. One round of R:

```python
screen = MirrorScreen.for_rounds(edit_names, rounds=R)   # alpha spent across rounds
```

Each candidate edit is one component; the champion prompt is the all-off configuration.
Accept the `admitted` set, feed `pruned` back to the proposer's rejected-candidate
memory. Never accept on a point comparison: at a measured 11.7% replay flip the point
rule false-adopts nearly every round (manuscript, Table 9).

## 4. Nightly CI screening with resume

```python
from mirrorcut.runners import Ledger, screen_with_ledger
screen_with_ledger(MirrorScreen(names, seed=0), tasks, run,
                   Ledger("artifacts/screen.jsonl"), budget=200)
```

The ledger is append-only; the nightly job picks up where the last one stopped, and any
interim read of `summary()` is valid. Wire the `pruned` list to fail the build if a
component the team believes in shows sustained harm evidence.

## 5. Choosing the cheaper arm first

```python
from mirrorcut import pairing_gain, UnpairedScreen
report = pairing_gain(pilot_pass_rates, effect=0.10)
Screen = MirrorScreen if report["recommend"] == "mirror" else UnpairedScreen
```

Run a pilot (20+ tasks, 3+ repeats each) with your champion config; `pairing_gain` tells
you whether the second invocation per row is worth paying on your task mix. On
homogeneous binary graders it usually is not; on graded scores with real task spread it
usually is.

## What a decision costs (rule of thumb)

| setting | rows to a decision | invocations | at $0.01/run | at $0.50/run |
|---|---|---|---|---|
| strong effect (~15pp), k=5 | 200-800 | 400-1,600 | $4-16 | $200-800 |
| moderate effect (~5pp), k=5 | 1,000-3,200 | 2,000-6,400 | $20-64 | $1,000-3,200 |
| live run of the manuscript (one pruning) | 199 | 398 | - | ~5h wall, model-side cost |

Budgets are per screen, not per component: cost does not grow with k. If a cell would be
unaffordable, screen a subset with the rest pinned.
