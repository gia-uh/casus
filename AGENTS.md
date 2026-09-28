# AGENTS.md

## What this repo is

A multi-agent LLM conflict simulator with a deterministic resolver. The engine
knows no domain vocabulary; a scenario is a directory of YAML data and Python
rules. `README.md` is the user view. `DESIGN.md` holds the architecture and the
reason behind each rule.

It exists to be shown and run in front of an audience of non-engineers. That shapes
every trade-off: legibility of the transcript beats cleverness, and a recorded run
that replays offline beats a live call that might time out on stage.

## Who it is for

A class on how modern AI is used for defence analysis and strategic simulation, and
students who want to re-run it on a laptop against a local 27–32B model.

## What done means

`make test` passes. That is the gate; nothing else claims to be one.

Three checks the suite cannot make, so they are commands a person runs:

- `uv run casus run scenarios/smoke --turns 1` — the endpoint really answers.
- `CASUS_REFERENCE_RUN=<repo>/runs/caribbean-lingo-101.jsonl uv run pytest tests/test_migration.py`
  — the reference ruleset still reproduces v1's recorded Caribbean run. It needs
  the recording and the private scenario, which git does not carry, so CI skips it.
- Open the bundled HTML in a browser and step through it. A green suite does not
  catch a map that renders at zero height.

## The rule the design serves

**The language model never computes a quantity.** Every number comes from a
scenario's rules, which change state only through the proxy's mutation calls,
with one seeded generator. The model declares intent and argues for it.

The invariants are tests rather than prose: the engine core (`state`, `proxy`,
`ruleset`, `resolver`) does no I/O, the narrator cannot change the state digest,
the validator rejects a rule that bypasses the ledger, and the ledger replays to
the recorded final state. If you are about to let a model emit a number that
feeds back into state, that is the moment to stop and reread the design doc.

## Where everything lives

- `src/casus/` — the modules. `README.md` has the one-line responsibility of each.
  There is no LLM plumbing here: `lingo` owns the transport, the structured call
  and the parsing. A model that returns something unusable is a lingo bug and
  gets fixed in lingo, not worked around here.
- `tests/` — one file per concern. `tests/reference/` holds v1's physics tests,
  run against the reference ruleset through an adapter (`reference_rules.py`)
  that keeps v1's world shape (`tests/v1shape.py`).
- `scenarios/` — one directory per scenario, data plus rules. `smoke/` and
  `reference/` ship; class scenarios live outside the repo behind the gitignored
  `scenarios/private` link, and the provenance tests skip when it does not
  resolve. See `scenarios/README.md`.
- `ui/` — `replay.html` and the generated `worldmap.json`.
- `tools/` — one-shot generators. Their output is committed; they are not imported.
- `runs/` — recorded transcripts kept for the class.

## Conventions

- Python 3.12+, English throughout. Conventional commits, one logical change each.
- Frozen dataclasses for state. A rule changes state only through `s.add`,
  `s.set` and the other mutation calls; the static validator rejects anything
  else.
- All randomness comes from the one `random.Random(seed)` a rule reaches as
  `s.rng`. The validator rejects `import random`.
- Every identifier is English, a scenario's included. Its `display.labels`
  carry the language.
- Every LLM call and its raw response is written to the transcript before the
  result is used.
