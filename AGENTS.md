# AGENTS.md

## What this repo is

A multi-agent LLM wargame harness with a deterministic resolver. `README.md` is the
user view. `DESIGN.md` holds the architecture and the reason behind each rule.

It exists to be shown and run in front of an audience of non-engineers. That shapes
every trade-off: legibility of the transcript beats cleverness, and a recorded run
that replays offline beats a live call that might time out on stage.

## Who it is for

A class on how modern AI is used for defence analysis and strategic simulation, and
students who want to re-run it on a laptop against a local 27–32B model.

## What done means

`make test` passes. That is the gate; nothing else claims to be one.

Two checks the suite cannot make, so they are commands a person runs:

- `uv run python -m casus.llm --smoke` — the configured endpoint really answers.
- Open the bundled HTML in a browser and step through it. A green suite does not
  catch a map that renders at zero height.

## The rule the design serves

**The language model never computes a quantity.** Sustainment, attrition, detection,
suppression and occupation ratios live in `rules.py` as pure functions with a seeded
RNG. The model declares intent and argues for it.

Two invariants enforce it, and both are tests rather than prose:
`rules.py` imports nothing that does I/O, and the narrator cannot change the state
digest. If you are about to let a model emit a number that feeds back into state,
that is the moment to stop and reread the design doc.

## Where everything lives

- `src/casus/` — the six modules. `README.md` has the one-line responsibility of each.
- `tests/` — one file per concern; `test_rules_*.py` is split by rule family.
- `scenarios/` — YAML data, never code. `smoke.yaml` ships; class scenarios live
  outside the repo behind the gitignored `scenarios/private` link, and the
  provenance tests skip when it does not resolve. See `scenarios/README.md`.
- `ui/` — `replay.html` and the generated `worldmap.json`.
- `tools/` — one-shot generators. Their output is committed; they are not imported.
- `runs/` — recorded transcripts kept for the class.

## Conventions

- Python 3.12+, English throughout. Conventional commits, one logical change each.
- Frozen dataclasses for state. Nothing mutates in place inside `rules.py`.
- All randomness comes from the one `random.Random(seed)` threaded through
  `resolve`. A module-level `random` call is a bug even when tests pass.
- Every LLM call and its raw response is written to the transcript before the
  result is used.
