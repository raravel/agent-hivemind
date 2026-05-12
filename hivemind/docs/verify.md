# Verification commands

Commands the `/hv:task` orchestrator runs to confirm a task is complete.
Each stage is independent; run in any order.

## lint

Static analysis. Fails on any reported issue.

```bash
python3 -m ruff check src/ tests/
```

## type

Type-checks the implementation (not tests — tests are intentionally loose).

```bash
python3 -m mypy src/
```

## test

Full test suite (unit + integration). Must fully pass.

```bash
python3 -m pytest
```

## build

Wheel build verification. Catches packaging regressions.

```bash
python3 -m build --wheel
```

## completion

A task is considered done when:

- all four stages above pass on the current branch
- the task's completion criteria checklist is fully `[x]`
- the 4-axis review rubric has `correctness >= 7`, `spec_compliance >= 7`, `safety >= 8`
- `hv harness-score show -p agent-hivemind --if-fresh 7d` either exits 0
  (cached score is fresh) or the task explicitly refreshed the score
