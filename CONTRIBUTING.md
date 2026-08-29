# Contributing

## Rules

1. **Fictional data only** in tests, examples, and issue reports.
2. Venue conclusions must come from `scripts/jurisdiction.py`, not from model memory.
3. New court / cap / local-override data needs a source citation in the JSON and a `--selftest` case.
4. Do not auto-detect special zones from address keywords.
5. If a court cannot be locked, keep `precise: false` and lower confidence. Never invent a unique court name.

## Dev

```console
python scripts/jurisdiction.py --selftest
```

Change data or rules → add a selftest case → all  cases must pass before merging.

## Pull requests

- Small, reviewable diffs
- Update README / CHANGELOG when behavior changes
- CI must pass on Ubuntu, Windows, and macOS across Python 3.10–3.12
