# casus

A multi-agent wargame where language models play the nations and a deterministic
resolver decides what happens.

Each actor is an LLM with a private briefing, private objectives and a partial,
deliberately noisy view of the world. It declares one to three actions per turn
from the scenario's closed vocabulary and argues for them. Everything countable
is computed by the scenario's rules, in Python, with one seeded random
generator. The model never does arithmetic.

The engine itself knows no domain words. A scenario is a directory: the data in
`scenario.yaml`, the physics in `rules.py`. The shipped reference ruleset is the
original wargame physics (fuel, Lanchester attrition, air-defence suppression,
the force-to-population ratio needed to hold ground), and a scenario uses it with
one line.

Runs are written to a JSONL transcript that carries every prompt, every
declaration, every event and every change to the state with the rule that made
it, so a run replays exactly without touching an API, a reader can see the text
that produced each decision, and "what moved this number" is a query.

## Install and run

```bash
uv sync
export BASE_URL=https://openrouter.ai/api/v1
export API_KEY=$(cat ~/.config/openrouter.token)
uv run casus validate scenarios/reference
uv run casus run scenarios/reference --seed 42 --out runs/run-42.jsonl
uv run casus verify runs/run-42.jsonl
uv run casus score runs/run-42.jsonl
uv run casus bundle runs/run-42.jsonl --out demo.html
uv run casus serve                       # the app on http://127.0.0.1:8321, this machine only
```

The transport is [lingo](https://github.com/gia-uh/lingo): casus has no LLM
plumbing of its own, so the endpoint, the structured-output call and the parsing
are lingo's, configured through lingo's own environment convention. Players are
27–32B-class models by default, so the same scenario runs against a local server
with one variable changed:

```bash
export BASE_URL=http://localhost:11434/v1   # Ollama
export API_KEY=ollama
```

Check the endpoint before a run. This one talks to the real service, so it is a
command you type, not a test:

```bash
uv run casus run scenarios/smoke --turns 1 --no-narrate
```

## What the pieces are

| Module | Responsibility |
|---|---|
| `state.py` | The world as frozen dataclasses with no domain vocabulary, canonical JSON, a stable digest |
| `proxy.py` | The surface a rule sees: views, `Ref`s, the mutation calls, the ledger |
| `ruleset.py` | The `@rule`, `@offer` and `@view` decorators and the registry |
| `resolver.py` | One turn: five phases in a fixed order, atomic on a failing rule. No I/O, no LLM |
| `scenario.py` | Loads a scenario directory; runs the validator on load |
| `validate/` | Static checks on the rules source, a dry turn, and scenario invariants |
| `players.py` | One LLM per actor: private briefing, the scenario's view and offer, validated actions |
| `actions.py` | The declaration type built from the scenario: invalid states are unrepresentable |
| `display.py` | Labels, bands and ladder from the scenario's `display` block |
| `narrator.py` | Turn narration. Read-only on state, and a test enforces it |
| `engine.py` | Turn loop, transcript, replay verification |
| `score.py` | Scores a run against the engine's own claims |
| `studies.py` | What is under runs/ and how far each run got |
| `bundle.py` | Transcript + map → one self-contained HTML replayer |
| `server/` | The local app: the shell, the scenario and run endpoints |

Scenarios live under `scenarios/`. `smoke/` exercises every call a rule can make
and is not a model of anything; `reference/` holds the reference ruleset and a
small public scenario that runs on it. Scenarios built for a particular class or
study are kept outside the repo — they carry sourced figures about real states
and belong with the people who can read them in context. `scenarios/README.md`
says how to write one and how to point the engine at them, and the provenance
tests run against them when they are present.

## What it is not

Not a predictor. A wargame enumerates branches and exposes assumptions; anyone who
reports its output as a forecast has misread it. Regions and force aggregates are
the finest granularity in the model, deliberately: `casus` reasons about whether a
campaign is sustainable and what it costs, not about how to conduct one.

## Accuracy claims

Three, each mechanically checkable:

1. **Reproducibility.** `casus verify <transcript>` re-derives the whole state
   trajectory from the recorded responses and fails loudly on any divergence.
2. **External branch agreement.** The scenario's branches are compared against a
   published open-source analysis, not against our own expectations.
3. **Physical plausibility.** Emitted quantities sit inside ranges from cited
   public sources. A scenario states its sources or fails its own test suite.

## Where the numbers come from

Nothing in this repo is classified, and nothing in it came from anywhere but the
open record. A scenario that carries figures about real states carries a
`source:` key on every one of them, resolving to a document a reader can open. A
run that cannot say where its numbers came from is not evidence of anything, and
this is the mechanism that keeps that honest.

MIT licensed. Built at the AI research group of the University of Havana for a
class on how AI is used in defence analysis and strategic simulation.
