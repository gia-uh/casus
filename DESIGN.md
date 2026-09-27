# casus — a multi-agent LLM wargame harness

## Purpose

A runnable artifact for a one-hour class to senior decision-makers on how modern
AI is used for defence analysis, strategic simulation and wargaming. The harness
has to do three jobs at once:

1. **Teach the mechanism.** A viewer must be able to see exactly what each model
   was told, what it decided, and which part of the outcome the model did *not*
   decide. The transcript is the teaching material, not a by-product.
2. **Run live without failing on stage.** A recorded run replays instantly and
   deterministically; a live run is a separate, optional button.
3. **Be reproducible by a student on a laptop.** Players are 27–32B-class models
   reachable over an OpenAI-compatible endpoint, so the same run works against
   OpenRouter, LM Studio or Ollama with one environment variable changed.

Python 3.12+, `uv`. Code, identifiers and docs in English.

## The one rule the whole design serves

**The language model never computes a quantity.** Fuel consumption, attrition,
force-to-population ratios, air-defence suppression, detection and civilian
distress are computed by pure functions with a seeded RNG. The model declares
*intent* and argues for it; the resolver decides what happens.

This is not a stylistic preference. It is the only way the artifact can answer
"how accurate is this?" with something other than a shrug: the numeric layer is
auditable and testable, the model layer is legible, and the boundary between them
is enforced by a test rather than by discipline.

Corollary, stated as an invariant the test suite checks: the narrator sees the
resolved state and writes prose about it. It cannot write to state at all.

## Components

Six modules, each independently testable, each answerable in one sentence.

| Module | What it does | Depends on |
|---|---|---|
| `state.py` | The world as dataclasses; JSON round-trip | — |
| `rules.py` | `(state, actions, seed) → (state', resolutions)`; pure, no I/O | `state` |
| `players.py` | One LLM per actor; private briefing + partial view → validated actions | `state`, `llm` |
| `narrator.py` | Resolved state → public news ticker. Read-only on state | `state`, `llm` |
| `engine.py` | Turn loop, seeding, JSONL transcript, replay | all |
| `llm.py` | One function against any OpenAI-compatible endpoint | — |

Plus `scenarios/*.yaml` (data, not code) and `ui/` (a single-file HTML replayer).

### `state.py`

```
WorldState
  turn: int
  actors: dict[str, ActorState]
  regions: dict[str, RegionState]
  forces: list[Force]
  relations: dict[tuple[str,str], int]      # -100..100
  log: list[Resolution]                     # what happened last turn, public

ActorState
  id, name
  fuel_days: float                          # days of military sustainment
  munitions: float                          # abstract stockpile, 0..100
  political_capital: float                  # 0..100, leadership's room to act
  domestic_support: float                   # 0..100
  intl_legitimacy: float                    # 0..100
  isr: float                                # 0..1, quality of its picture
  escalation_rung: int                      # highest rung reached, 0..7

RegionState
  id, name, owner, adjacency: list[str]
  centroid: (lat, lon)                      # for the map
  control: float                            # 0..100, owner's effective control
  infrastructure: float                     # 0..100
  civilian_distress: float                  # 0..100
  population: int
  terrain: "urban" | "rural" | "coastal" | "sea"

Force
  id, owner, kind, strength, readiness, region, posture
  kind: ground | air | naval | air_defense | irregular
  posture: garrison | offensive | defensive | dispersed | hardened
```

Everything serializes to plain JSON. A `WorldState` is fully described by its
JSON; there is no hidden state anywhere in the engine.

### The escalation ladder

Eight rungs, fixed, and every action maps to exactly one:

```
0 rhetoric          1 economic          2 show of force     3 interdiction
4 covert / cyber     5 limited strikes   6 air campaign      7 ground invasion
```

The ladder is the spine of the pedagogy. Plotting rung-per-actor-per-turn is the
one chart a room of directors will remember, and it is exactly the measurement
Rivera et al. used to show that off-the-shelf models escalate.

### Action vocabulary

A closed set. The model picks from it; it cannot invent an action.

`statement`, `sanction`, `mobilize`, `deploy`, `disperse`, `harden`, `blockade`,
`cyber`, `covert`, `strike`, `air_campaign`, `invade`, `supply`, `negotiate`,
`concede`, `hold`.

Each carries typed parameters (target region, target actor, forces committed,
intensity 1–3). Each turn an actor declares one to three actions plus a private
rationale.

### `players.py` — the contract with the model

Each player receives, and nothing else:

- its **private briefing**: who it is, its objectives, its red lines, its
  domestic constraints;
- its **partial view** of the world: its own forces exactly; other actors' forces
  perturbed by deterministic noise scaled by `1 - isr`;
- the **public log** of last turn;
- the **action schema** and the legal action list.

It returns strict JSON: `{actions: [...], rationale: str, assessment: str}`.
Validation failure triggers one retry carrying the validation error, then falls
back to `hold`. Every prompt and every raw response goes into the transcript.

Fog of war is real, not decorative: a player with low ISR is shown wrong numbers,
and the class gets to watch it reason confidently from them.

### `rules.py` — what the deterministic layer actually computes

Each of these is a named function with tests, and each is a slide:

- **Sustainment.** Active forces burn `fuel_days` by kind and posture. A
  `blockade` cuts inflow; a `supply` action from a third actor restores it.
  Running out forces postures down to `garrison` regardless of what the model
  wants — the first place where the model's intent visibly loses to arithmetic.
- **Attrition.** Lanchester square-law exchange between engaged forces, modified
  by air superiority, surviving air defence, terrain, and an irregular-defender
  multiplier in `urban` and `rural`.
- **Air-defence suppression.** Sustained strikes degrade `air_defense` strength;
  below a threshold the attacker loses its attrition penalty and switches to
  cheap munitions. Calibrated so suppression takes four to five turns, matching
  the publicly reported Iran campaign.
- **Detection.** Seeded noise applied to each actor's view of every other, scaled
  by ISR. Deterministic given the seed.
- **Civilian distress and legitimacy.** Distress rises with infrastructure damage
  and fuel deprivation. Distress costs the attacker `intl_legitimacy` and the
  defender `domestic_support`, on different curves.
- **Occupation.** Holding a region needs one security member per fifty
  inhabitants (the stability-operations rule of thumb CSIS applies to Cuba, from
  *Parameters*). Short of that ratio, `control` decays every turn and irregular
  forces regenerate. An invader that takes ground without the ratio watches the
  number fall on screen.

### `narrator.py`

One LLM call per turn. Input: the public state and the resolutions. Output: a
short news ticker. It has no write path to state, and `test_narrator_cannot_mutate`
asserts that the state hash is unchanged across the call.

### `engine.py` and the transcript

The transcript is JSONL, one record per event, kinds: `scenario`, `state`,
`prompt`, `response`, `action`, `resolution`, `narrative`, `end`. It carries the
full prompt and the raw completion for every call. A run is replayable from it
with no API access, and `--replay` re-derives the entire state trajectory from
the recorded responses and asserts it matches byte for byte. If that test fails,
some non-determinism leaked into the resolver.

### `llm.py`

```python
def complete(model: str, messages: list[dict], schema: dict) -> dict
```

One OpenAI-compatible POST. `CASUS_BASE_URL` and `CASUS_API_KEY` select the
backend; the per-actor `model` string comes from the scenario file. Default is a
Qwen3 32B-class model over OpenRouter, so a student swaps the base URL for
`http://localhost:1234/v1` and runs the same scenario against LM Studio.

### `ui/` — the replayer

A single HTML file, no build step, no dependencies at load time, matching the
house deck format (16:9, `cqw` units, dark, keyboard-driven). It loads a
transcript and shows, per turn:

- a **world map** in SVG (Natural Earth 110m, simplified once by a script into
  `worldmap.json`) with actor colours, force markers on region centroids and a
  Caribbean inset;
- the **escalation chart**, rung per actor over turns;
- **resource bars** per actor;
- the **action log** with each model's rationale in its own words;
- a **prompt drawer** showing exactly what that model saw before deciding.

The prompt drawer is the single most valuable element for this audience: it turns
"the AI decided to blockade" into "here is the text that produced that word".

## How accuracy is claimed

A wargame does not predict. It enumerates branches and exposes assumptions.
So the artifact makes three claims, each mechanically checkable:

1. **Reproducibility.** Same seed and same recorded responses reproduce the state
   trajectory exactly. Different seeds produce a spread that gets reported rather
   than hidden.
2. **External branch agreement.** The five CSIS scenarios for Cuba — pressure
   campaign, internal collapse, decapitation, limited air offensive, runaway
   escalation — must emerge from initial conditions without being handed to the
   models as input. Branches the engine cannot reach are a finding about the
   engine, and get written down.
3. **Physical plausibility.** Quantities the engine emits sit inside the ranges
   public sources give: occupation force at or above 100,000 for ten million
   people, air-defence suppression in four to five turns, force counts for the
   FAR at roughly 50,000 active and 39,000 reserve.

## Vertical slices

1. **VS1 — thinnest end-to-end path.** Two actors, three regions, three turns,
   terminal output, one real API call per player per turn, transcript written.
   No map, no narrator, minimal rules (sustainment and attrition only).
2. **VS2 — the deterministic core.** Full `rules.py` with tests, including the
   occupation ratio and air-defence suppression. Replay determinism test.
3. **VS3 — scenarios as data.** YAML loader, the Caribbean 2026 scenario, actor
   briefings, seeds for the five branches.
4. **VS4 — the replayer.** World map, escalation chart, prompt drawer.
5. **VS5 — the runs.** Three recorded runs plus the analysis that goes in the deck.

## Out of scope

No real-time operation, no connection to any live data feed, no targeting-level
resolution: regions and force aggregates are the finest granularity, deliberately.
The engine models whether a campaign is sustainable and what it costs, not how to
conduct one. No classified or non-public source is used anywhere; every number in
the Caribbean scenario traces to a citation in the dossier.
