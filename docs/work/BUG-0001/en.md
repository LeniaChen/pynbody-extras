# BUG-0001: Result execution tree renders only the root node

## Context

`Result.execution_tree` is the runtime view of a calculator run. It should show
the same node relationships as `CalculatorBase.dependency_tree` and
`Result.report_node_tree()`, with execution metadata (time, cache, observer) on
each line. The default `rich` HTML repr renders this text inside its
"Execution tree" section.

## Actual behavior

Using the shared-filter pipeline from `tests/calculate_helpers.py`:

```text
p<combined>  [2.84 ms; cache=store]
```

`result.execution_tree` has one line. `result.report_node_tree()` has five:

```text
p<combined>
├─ MassSum<property>
│  └─ RBelow<filter>
└─ TempMean<property>
   └─ RBelow<filter>
```

In the `rich` HTML repr, the "Execution tree" `<pre>` contains the same single
line. The `simple` HTML repr lists `.execution_tree` as a drill-down attribute
instead of inlining it; that layout difference is intentional and is not part of
this bug.

## Expected behavior

The execution tree should render the full graph, with the same parent/child
shape as the node tree:

```text
p<combined> [...]
├─ MassSum<property> [...]
│  └─ RBelow<filter> [...]
└─ TempMean<property> [...]
   └─ RBelow<filter> [...]
```

The shared `RBelow` node appears on both branches, but its children are expanded
only once. A repeated occurrence is shown as a hit rather than walked again.

## Reproduction

```python
import sys

sys.path.insert(0, "tests")

from calculate_helpers import make_pipeline, make_sim

pipeline = make_pipeline()
result = pipeline.run(make_sim())

print(result.execution_tree)      # one line
print(result.report_node_tree())  # five lines
```

## Root cause

`tree_lines()` in `pynbodyext/core/calculate/display.py` evaluates
`children(root)` once before `walk()` and again inside `walk()`:

```python
root_children = list(children(root))   # first call
...
walk(root, "", 1)                      # calls children(root) again
```

`ResultQuery.execution_tree()` passes a stateful `children_of()` callback:

```python
if current.node_id in rendered_nodes:
    return []
rendered_nodes.add(current.node_id)
return ResultQuery.display_children_of(result, current)
```

The first call adds the root to `rendered_nodes`; the second call therefore
returns `[]`, so the root's children are never walked. This violates the
implicit contract that `tree_lines(children=...)` is a pure accessor.

## Acceptance criteria

- [ ] `result.execution_tree` includes every reachable node for the fixture
      above (five lines, including the shared filter on both branches).
- [ ] A shared node is rendered again as a hit, but its children are not
      expanded a second time.
- [ ] The parent/child shape matches `result.report_node_tree()` for the same
      result.
- [ ] The `rich` HTML card's Execution tree `<pre>` contains `MassSum`,
      `TempMean`, and `RBelow`.
- [ ] `max_depth=0` still uses the shared wording `... N nodes hidden`.
- [ ] A regression test fails on the current code and passes after the fix.

## Test plan

- Extend `tests/test_calculate_render.py` with a fixture using
  `make_pipeline()`.
- Assert the execution tree and node tree have the same number of lines.
- Assert all three node labels appear in the execution tree.
- Assert the `rich` HTML repr contains the child labels inside the
  "Execution tree" section.
- Run `make check` and `make test-all`; run `ruff` and `mypy`.

## Design notes

At minimum, `tree_lines()` should evaluate `children(root)` once and pass that
list into `walk()`. Making `execution_tree`'s callback idempotent, or moving the
"already expanded" tracking out of the `children` callback, would make the
contract explicit and prevent the same bug from returning.

### Chosen fix

Both, kept small:

1. `tree_lines()` evaluates `children(root)` once and passes the list into
   `walk()`; `walk()` now takes a node's children rather than the node, so
   `children` is called at most once per rendered line. The docstring states the
   call-order contract (pre-order, `label` before `children`, `children` at most
   once per line).
2. `ResultQuery.execution_tree()` decides "first occurrence vs. repeat" in its
   `label` callback (`labelled_nodes` / `collapsed_nodes`). `children_of()` only
   reads that state, so calling it twice for the same line returns the same
   children.

The same double call also dropped the `... N nodes hidden` lines for
`max_depth >= 1`: `execution_tree(max_depth=1)` and `max_depth=2` rendered
only the root line. The fix covers that case too, and it has its own test.

## Non-goals

- Redesigning the execution-tree labels or performance metadata.
- Changing the `simple` HTML card's drill-down layout.
- Adding new cache or observer fields.

## Open questions

- Should a repeated shared node be marked explicitly (for example `[hit]`), or
  keep the existing `hit_occurrence` behaviour? Preserve the current behaviour
  unless the fix requires a change.
  - Answer: the fix did not require a change; a repeat still renders as
    `label  [cache=hit]` with no subtree.
