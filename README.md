# casus

A multi-agent wargame where language models play the nations and a deterministic
resolver decides what happens.

Each actor is an LLM with a private briefing, private objectives and a partial,
deliberately noisy view of the world. It declares one to three actions per turn
from a closed vocabulary and argues for them. Everything countable — fuel,
attrition, air-defence suppression, the force-to-population ratio needed to hold
ground — is computed by pure functions with a seeded RNG. The model never does
arithmetic.

Runs are written to a JSONL transcript that carries every prompt and every raw
completion, so a run replays exactly without touching an API, and a reader can see
the text that produced each decision.

## Install and run

```bash
uv sync
export CASUS_BASE_URL=https://openrouter.ai/api/v1
export CASUS_API_KEY_FILE=~/.config/openrouter.token
uv run casus run scenarios/smoke.yaml --seed 42 --out runs/run-42.jsonl
uv run casus verify runs/run-42.jsonl
uv run casus bundle runs/run-42.jsonl --out demo.html
```

Players are 27–32B-class models by default, so the same scenario runs against a
local server with one variable changed:

```bash
export CASUS_BASE_URL=http://localhost:1234/v1   # LM Studio
export CASUS_API_KEY=
```

Check the endpoint before a run. This one talks to the real service, so it is a
command you type, not a test:

```bash
uv run python -m casus.llm --smoke
```

## What the pieces are

| Module | Responsibility |
|---|---|
| `state.py` | The world as frozen dataclasses, canonical JSON, a stable digest |
| `rules.py` | `(state, actions, seed) → (state', resolutions)`. Pure. No I/O, no LLM |
| `players.py` | One LLM per actor: private briefing, fog-of-war view, validated actions |
| `narrator.py` | Turn narration. Read-only on state, and a test enforces it |
| `engine.py` | Turn loop, transcript, replay verification |
| `llm.py` | One POST against any OpenAI-compatible endpoint |
| `bundle.py` | Transcript + map → one self-contained HTML replayer |

Scenarios are YAML under `scenarios/`. `smoke.yaml` ships with the engine and is
not a model of anything. Scenarios built for a particular class or study are kept
outside the repo — they carry sourced figures about real states and belong with
the people who can read them in context. `scenarios/README.md` says how to point
the engine at them, and the provenance tests run against them when they are
present.

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
