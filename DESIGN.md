# casus — design

## Purpose

A runnable artifact for teaching how modern AI is used in defence analysis,
strategic simulation and wargaming. It has three jobs:

1. **Teach the mechanism.** A viewer can see what each model was told, what it
   decided, and which part of the outcome the model did *not* decide. The
   transcript is the teaching material.
2. **Run without failing on stage.** A recorded run replays offline and
   deterministically; a live run is optional.
3. **Be reproducible by a student on a laptop.** Players are 27–32B-class models
   behind any OpenAI-compatible endpoint, so the same run works against
   OpenRouter, LM Studio or Ollama with one environment variable changed.

The full specification is the v2 design doc in the workspace vault,
`vault/Atlas/Architecture/2026-09-28-casus-general-conflict-simulator-design.md`.

## The rule the design serves

**The language model never computes a quantity.** Every number is computed by a
scenario's rules, in Python, with one seeded random generator. The model declares
intent and argues for it; the rules decide what happens. That is what lets the
artifact answer "how accurate is this?" with something checkable: the numeric
layer is tested and replayable, the model layer is legible, and a test enforces
the boundary between them.

The narrator reads the resolved state and writes prose about it. A test asserts
the state digest is unchanged across the call.

## The engine knows no vocabulary

v1 knew about fuel, air defences and occupation ratios, so every scenario with a
different mechanic needed an engine change. v2 moves the physics out. The engine
knows actors holding named resources, places with named attributes and
adjacency, entities with an owner, a kind and a place, the actions a scenario
declares, five fixed phases, and rules that change state through one recording
API. None of the names mean anything to it; `test_state.py` fails if `state.py`
mentions a domain word.

A scenario is a directory: `scenario.yaml` holds the data (actors, resources,
places, entities, actions, briefings, how to display it all), and `rules.py`
holds the physics. Whoever changes forces and briefings never opens the Python.

## Five phases, in a fixed order

```
legality → upkeep → movement → contest → consequences
```

A scenario puts rules in phases; it does not choose their order. The fixed order
is what makes "what has happened so far this turn" exact: a rule sees the events
emitted by earlier phases and earlier rules, and nothing else. Within a phase,
rules run in declaration order. Before any rule runs, the resolver sorts the
actions into a canonical order, clamps intensity to each action's declared
bounds, drops a place from an action that takes none, and rejects what no
scenario could accept (an undeclared type, an unknown actor, place or target).

A rule that raises abandons the whole turn, and the transcript records the error.
A half-applied turn on disk would replay as a plausible state nobody produced.

## The rule surface, and the ledger

A rule reads the world through views and changes it only through mutation calls:
`add`, `set`, `transfer`, `decay`, `move`, `spawn`, `despawn`. Attribute access on
a view returns a `Ref`, the value plus the path it came from, so `s.add(ref, -8)`
knows what it changes. Every mutation writes `{rule, ref, before, after, turn,
phase}` to the ledger, and the ledger goes into the transcript.

The ledger exists because of v1's ratchet. On 2026-09-27 Cuban domestic support
fell to zero by turn six with every actor holding, and survived 196 tests and two
scored runs, because nothing could answer "what moved this number". Now that is
a query over the transcript. `test_engine.py` replays the ledger from the initial
state and requires it to land on the recorded final state; if it does not, some
path changed a value without recording it.

Two hooks sit beside the rules. `@offer` says which action types an actor may
declare this turn and at which places; it runs read-only, and the declaration
schema is built from it, so an action the actor cannot take cannot be expressed.
`@view` turns a throwaway copy of the world into what the actor believes; it is
the fog of war, and its changes never reach the world or the ledger.

## Everything else reads the display block

Players, narrator, score and viewer never name a resource. They read the
scenario's `display` block: which resources stand in the bars and the CLI line,
bands that stand in for exact numbers in another actor's prompt, labels in the
scenario's language, the escalation ladder if there is one, what the map colours
and draws, and which events the narrator leaves out. Identifiers stay English;
labels carry the language.

## The validator

Three layers, because each catches what the others cannot.

- **Static**, over the source, before any of it runs: no direct assignment to
  state (it would bypass the ledger), no import outside `casus.ruleset` and
  `math`, no `open`, `eval`, `id`, `hash` or dunder access, no module state
  written from a rule, no unknown phase, no signature that does not match its
  decorator. `Scenario.from_parts` runs it on every load, including a scenario
  rebuilt from a transcript.
- **Dynamic**, one dry turn with everyone holding: names a rule uses that the
  scenario does not declare, rules on action types nobody can declare, module
  values a turn changed, and a digest that differs between two processes started
  with different `PYTHONHASHSEED` values. It needs two processes because string
  hashing, and so `set` order, is fixed for the life of one. `Scenario.load`
  runs it.
- **Invariants**, on demand (`casus validate`): a quantity declared
  `monotone: false` must rise and fall somewhere across one holding run and
  eight random-policy runs, and in the holding run none may be driven to a bound
  and stay there. Holding alone cannot answer whether a variable can go back,
  because when everyone holds nobody pushes it. This layer rejects the v1
  Caribbean physics as ported, which is the evidence it catches the real defect.

A finding carries its reason, so an author (or design mode's agent) fixes it in
one pass. None of this is a sandbox: a rules file still runs in the engine's
process.

## Transcript and replay

The transcript is JSONL. It carries the scenario data and its rules source, every
state with its digest, every prompt with what the actor was offered, every
validated declaration, every action with its rationale, every event, every
mutation, and every narrative. `casus verify` rebuilds the scenario from the
transcript alone, re-derives the run from the recorded declarations, and fails
naming the first turn and field that differ. It compares the state content as
well as the digest, so a hand-edited state whose digest was left alone fails too.

Within a turn, the random draws for every actor's view happen first, in sorted
actor order, and only then do the model calls go out together. Determinism and
concurrency are separated on purpose.

## The reference ruleset

v1's physics lives in `scenarios/reference/rules.py`: sustainment, Lanchester
attrition, air-defence suppression, mobilisation, supply, movement, the
escalation high-water mark, the occupation ratio, civilian distress and
legitimacy. Every coefficient is a module constant with a comment giving its
provenance. A scenario uses it with `rules: reference`. The physics stays public
and tested in CI even though the class scenario that uses it is private.

The port is bit-exact: replaying the recorded Caribbean run on it reproduces all
thirteen states, 1,560 numeric comparisons with a worst difference of zero
(`tests/test_migration.py`, local only, because the recording and the class
scenario are not in git). It keeps two v1 quirks on purpose, both commented in
the code: the air-defence divisor reads strength from before the same turn's
suppression, and `mobilize` takes no place.

## How accuracy is claimed

A wargame does not predict. It enumerates branches and exposes assumptions, so
the artifact makes three checkable claims:

1. **Reproducibility.** The same seed and the same recorded declarations
   reproduce the trajectory exactly. `casus verify` checks it.
2. **External branch agreement.** Where a published open-source analysis has
   enumerated the branches of a situation, those branches must emerge from the
   initial conditions without being handed to the models. A branch the engine
   cannot reach is a finding about the engine.
3. **Physical plausibility.** Emitted quantities sit inside the ranges a
   scenario's `display.plausibility` declares, each naming its source.
   `casus score` reports them.

## Out of scope

No real-time operation, no live data feed, no targeting-level resolution: places
and entity aggregates are the finest granularity, deliberately. The engine models
whether a campaign is sustainable and what it costs, not how to conduct one. No
classified or non-public source is used, and every numeric field in a class
scenario carries a `source:` a reader can follow; a test fails when one does not.
