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
export CASUS_API_KEY_FILE=~/.claude/openrouter.token
uv run casus run scenarios/caribbean-2026.yaml --seed 42 --out runs/run-42.jsonl
uv run casus replay runs/run-42.jsonl
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

Scenarios are YAML under `scenarios/`. Every force count and population figure
carries a `source:` key resolving to an entry in `scenarios/SOURCES.md`.

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
   public sources.

MIT licensed. Built for a class on how AI is used in defence analysis.
