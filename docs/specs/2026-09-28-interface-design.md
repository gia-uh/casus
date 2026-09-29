---
date: 2026-09-28
status: "slice 1 implemented (PR #7); slices 3-5 pending"
issue: https://github.com/gia-uh/casus/issues/5
scope: "the casus app: a shell, a game viewer for live and recorded runs, the three modes as screens, settings, and the server behind them"
extends: "the v2 design, section 'The interface' (vault/Atlas/Architecture/2026-09-28-casus-general-conflict-simulator-design.md)"
---

# casus — the interface

## What this is for

casus is shown to rooms of people who are not engineers. They should be able to
watch five models argue a crisis turn by turn and see which part of the outcome
the models decided and which part the rules decided. Today the only way to
watch is `ui/replay.html`, a static page `casus bundle` fills after a run
finishes. Nothing can be started, watched live, authored or questioned from a
screen.

This spec turns casus into one local app with three modes, the same three the
v2 design names:

| mode | screen | what the person does |
|---|---|---|
| **run** | the game viewer | starts a run and watches it happen, or replays a recorded one |
| **design** | the workshop | edits a scenario, by hand or by asking the design agent |
| **evaluate** | the study | compares the runs of one scenario and asks the evaluate agent about them |

Every decision below was made on a clickable mockup with no backend, built
against the recorded run `caribbean-v2-repaired-101` and reviewed with Alex on
2026-09-28. The mockup embeds the private class scenario, so it is not in this
repository. A copy is kept with the class scenarios
(`casus-clase/mockups/casus-v2.html` in the private vault), and the numbers in
it are real because it plays a real transcript.

## The rule the interface serves

**One viewer, fed by transcript records.** The viewer never talks to the
engine. It consumes the same records the transcript already holds (`scenario`,
`state`, `prompt`, `declaration`, `action`, `event`, `mutation`, `narrative`,
`end`), and it gets them from one of two places:

- **live**, over a server-sent event stream while a run is being played;
- **recorded**, from the JSON `casus bundle` inlines into a single HTML file.

It is the same code in both cases. That keeps the property the project was
built around: a recorded run replays offline, off a USB stick, with no network,
and it looks exactly like the live one. A viewer that needed the server would
break the demo the first time a classroom's wifi did.

The consequence for every later decision: if the viewer needs a fact, that fact
must be in a record. The viewer computes nothing about the world. It draws what
the records say, and it may diff two recorded states to show what moved.

## The shell

A home screen with two shelves, then full-screen documents.

- **Scenarios.** One card per scenario directory under `scenarios/` (the
  private link included when it resolves): name, counts of actors, places and
  turns, the validator's verdict, and two buttons, **Run** and **Design**. A
  dashed card starts a new scenario from the template.
- **Studies.** A study is every run of one version of one scenario, where the
  version is a digest of the scenario data and rules source every transcript
  carries (the evaluate mode spec explains why the version matters). There is
  no new storage: the server groups the files in `runs/` by that digest, and a
  run's id is its file stem. A study card lists its runs, each with **View**,
  and has **Evaluate** and **Add runs**, which launches a batch of seeds.

Opening anything fills the screen. The top bar (brand, breadcrumbs, settings)
exists only when not presenting: `P` toggles presenter mode, which hides every
piece of chrome, and `Esc` leaves it. A laptop projected in a classroom shows
the scene and nothing else.

Routes are hash routes, so a bundle can use them without a server:
`#/`, `#/run/<scenario>`, `#/view/<run>`, `#/design/<scenario>`,
`#/study/<scenario>`.

## The game viewer

### Four beats per turn

A turn is four beats. Each fills the screen.

1. **Thinking.** The war room: one pane per actor, all visible at once, each
   writing its rationale as it arrives. A pane reads *thinking* until its
   first token, *writing* while text streams, and *ready* when its declaration
   is complete. Below the panes a small board shows the map, the escalation
   ladder and the standing bars, all from the state at the start of the turn.
2. **Declaring.** Every pane's actions are revealed at once, and the places
   they aim at pulse on the map.
3. **Resolving.** The command post: the map fills the screen, the five fixed
   phases light in order, then the turn's events arrive, then the largest
   changes animate from their value before the turn to their value after it.
   A strip along the bottom keeps each actor's declared actions in view.
4. **Dispatch.** The narrator's text for the day, set as a printed dispatch
   over the map, with the declared actions listed under it.

The war room is where the tension is: five models writing at once and the room
watching who finishes first. The command post is where the consequences are.
The first review offered each as the only layout, and Alex chose to switch
between them by beat.

### Declarations stay sealed until all are in

In beat 1 a pane shows the rationale streaming and a sealed placeholder where
the actions will go. The actions of all actors open together at beat 2, the
way simultaneous moves work in a board game. Hovering a place during beat 1
says the declarations are still sealed rather than revealing what is aimed
there.

This costs nothing in the engine. `run_async` already gathers the player calls
and writes every declaration only after all of them return
(`src/casus/engine.py`, the `asyncio.gather` in the turn loop). The only rule is
that the live stream carries the rationale text and never a partial action (see
"Streaming a declaration").

The alternative, each actor's action shown the moment it exists, was
considered. It is simpler, and the room would see one actor's move while
another is still deciding, which is exactly what the real players could not
see. If a class wants it, it is a viewer flag, not an engine change.

### Pacing

- **Live**, beats advance on their own: each beat lingers a moment after it
  finishes, then the next begins. The run's own speed sets the pace of beat 1.
- **Recorded**, the presenter's arrow key advances beats, never a clock. The
  animation inside a beat still plays; what waits for the key is the next
  beat. In beat 1 the first press finishes the typing and the second opens the
  declarations.

Two controls, because the review found one was not enough: **auto** decides
whether beats advance on their own (on by default live, off recorded), and
**space** freezes the scene where it is, in either mode. The mockup first
merged them, and a recorded run then froze its own resolution animation.

Keys: `→` next beat, `←` previous, `space` freeze, `P` presenter mode, `Esc`
leave presenter mode or go home. A row of day markers jumps to a turn.

### The place card

Hovering any place on any map (the war-room board, the command post, the
workshop's map) shows a card. With the map regions spec a place is a filled
region, and the whole region is the hover target. The card shows:

- the place's name, who controls it, its terrain and population, and which
  moment the card describes: at the start of day N, after resolving day N, or
  the initial state;
- each place attribute listed in `display.card`, as a bar and a number, with
  `before → after` once the turn is resolved. The colour says whether the
  change is good for the place, so a falling distress figure is green. Which
  attributes are worse when higher is scenario data (`display.worse_when_higher`),
  not a viewer rule;
- the entities there, each with owner, kind and strength, marked when one
  arrived or left that turn;
- what was declared against the place that day, by whom and at what intensity,
  or "still sealed" during beat 1;
- its neighbours and the source key its figures cite.

When a map redraws under a still pointer (at the reveal, at the end of
resolution) the card refreshes. Otherwise it would keep describing a moment the
screen has left.

### What each beat reads

| beat | records |
|---|---|
| thinking | `state` at turn start, `prompt` (model per actor), live `delta` messages |
| declaring | `action` (actor, action, rationale, assessment) |
| resolving | `event`, `mutation` (for the count shown), `state` after the turn |
| dispatch | `narrative` |

A recorded run has no `delta` messages, so beat 1 replays each rationale at a
seeded, per-actor typing speed. It is theatre, and it is the same every time.

`casus bundle` already keeps `action` records, which carry everything beat 2
shows, and drops `declaration` and `mutation` records to keep the file small.
The only addition is the mutation count the command post shows: the bundle
writes one small `ledger` record per turn carrying the count, and the ledger
itself stays in the transcript, where `casus verify` reads it.

## Live runs

`casus serve` starts the app on `127.0.0.1` and opens the browser. It is a
local tool for one person at a laptop; it has no accounts and does not listen
on other interfaces.

A run starts from **Run** on a scenario card, after a short form: seed, turns,
default model, and which study it joins (always the scenario's own). The server
then:

1. starts `engine.run_async` in a background task, writing the transcript to
   `runs/<scenario>-<seed>[-n].jsonl` as the CLI does;
2. passes it an observer, a new optional argument that receives every record
   at the moment it is written, plus the ephemeral `delta` messages;
3. publishes both to every subscriber of that run.

A browser subscribes with `GET /api/runs/<id>/events`. The server first sends
every record already in the transcript, then follows the live ones. A browser
that opens late, or reconnects after the wifi drops, catches up from the file
and continues. A finished run served this way is indistinguishable from a
recorded one, which is the point.

`delta` messages are never written to the transcript. They are how the text
got onto the screen, not part of what happened, and replay does not need them.

If a run fails (a rule raises, the endpoint dies), the transcript already
records the error. The viewer shows it on the turn where it happened, and the
run stays in its study as a failed run.

## Streaming a declaration

Players call `Engine.create`, which reaches lingo's `LLM.create`, which uses the
non-streaming `parse`. lingo streams only `LLM.chat`, through `on_token`. So
streaming a declaration as it is written is a change in lingo, and the v2
design already put it there.

What casus needs from lingo: `create` accepts an `on_token` callback and, when
one is given, streams with the same `response_format`, calls the callback per
content fragment, and returns the parsed model at the end exactly as it does
now. The feasibility check was run on 2026-09-27 against OpenRouter with
Qwen3-32B: structured output streamed as 438 fragments, the first after 1.5
seconds, with the parsed result unchanged.

What casus does with the fragments: a small incremental reader follows the JSON
as it grows and forwards only the characters inside the `rationale` string.
Actions come first in the declaration schema, so while the model is producing
them the pane reads *thinking*; the rationale then streams; the actions stay
sealed until the declaration record is written. No partial action ever reaches
the browser.

An endpoint that cannot stream structured output is not an error. The pane
reads *thinking* until the declaration arrives, then shows the rationale whole.
The game still plays. Only the typing is lost.

## The workshop (design mode)

Split screen: the design agent on the left, the artefact on the right.

- **Artefact tabs**: a form, `scenario.yaml`, `rules.py`, and a read-only map
  with adjacency drawn. The form is a structured view of the YAML: saving it is
  a whole-file write of `scenario.yaml` through the same validator the agent's
  writes go through. There is no second path into a scenario.
- **Status strip**: the runnable snapshot (the last version that validated)
  and the working copy (valid, not yet validated, or failing with its first
  finding). A failing write is kept, and cannot be run; this is the v2
  design's commit moment made visible.
- **Agent pane**: a chat where each tool call appears as a line with its result.
  The twelve tools are the ones the design mode spec lists: the v2 design's
  eleven and `assume`, which records a figure chosen by judgement as an
  explicit assumption. Nothing else. A validation failure shows in red and the agent's retry follows it, so
  the room sees the validator refuse an uncited number.

The agent itself (its system prompt, how it plans a change, how it fails) gets
its own spec. This one fixes the screen and the contract: the agent acts only
through those tools, and the screen shows every call.

## The study (evaluate mode)

Split screen again: the evaluate agent on the left, the study on the right.

- **Run cards**: each run in the study, with its label, action and mutation
  counts, and **View**.
- **A series chart**: one quantity of one actor across turns, one line per run,
  chosen from two selectors. The data comes from the `state` records, served by
  `GET /api/studies/<scenario>/series`, never computed by the agent.
- **Agent pane**: the evaluate agent's chat, with its tool calls shown the same
  way. Its tools are the fixed queries the evaluate mode spec lists; it runs no
  code of its own. When an answer is about a quantity, the chart switches to
  it, and any figure in an answer that no query returned is marked.

The mockup's question "why does one actor end with no domestic support" is the
case this mode exists for, and the answer came from the data: in the run
without the recovery rules the figure reaches zero on day 5 and no mutation
ever raises it; with them, the same seed bottoms out and recovers. Evaluate
works over a study and says so when a study is too small to separate signal
from chance.

The agent gets its own spec, like the design agent.

## Settings

The v2 design fixed the rules; this spec only places them on a screen, reached
from the top bar.

- Values live in `~/.config/casus/config.toml`. Environment wins over the file,
  and each field shows where its value came from.
- Fields: endpoint, OpenRouter token, Firecrawl token, default player model,
  agent model. They map onto the environment lingo already reads (`BASE_URL`,
  `API_KEY`).
- A secret is write-only: the field shows *configured* or *not set*, never the
  value, because a projected settings screen is a token in a photograph.
- **Test connection** makes one cheap call against the configured endpoint and
  reports the model that answered and the latency, or the error. Saving a
  string is not the same as checking it.
- A test greps a produced transcript and a produced bundle for the configured
  key material and fails if it finds any.

## The server

FastAPI, started by `casus serve`. It adds `fastapi` and `uvicorn` to the
dependencies. Server-sent events go out as a plain streaming response; no
event library is needed.

| method | path | what it does |
|---|---|---|
| GET | `/` | the app |
| GET | `/api/scenarios` | scenario cards, with the validator's verdict |
| GET | `/api/studies` | transcripts grouped by scenario |
| GET | `/api/studies/<scenario>/series` | per-turn values from `state` records |
| GET | `/api/runs/<id>` | a transcript's records, as the bundle keeps them |
| POST | `/api/runs` | start a live run; returns its id |
| POST | `/api/studies/<scenario>/runs` | start a batch of N seeds for the current version |
| GET | `/api/runs/<id>/events` | the record stream: the file so far, then live |
| GET/PUT | `/api/settings` | settings, secrets as *configured* or *not set* |
| POST | `/api/settings/probe` | the connection test |

Design and evaluate add their own endpoints in their own specs.

## The frontend

Plain HTML, CSS and JavaScript in `ui/`, with no build step and no package
manager. It replaces `ui/replay.html`.

- The scripts are classic scripts, not ES modules, loaded in a fixed order and
  attached to one global `Casus` namespace. The app loads them with `<script
  src>`; the bundle concatenates them inline, so `casus bundle` still writes
  one file that loads nothing from the network. The existing test that the bundle names no network URL
  keeps guarding that.
- Fonts come from the system stack in the bundle. The app may use web fonts
  when it is online; the bundle must not depend on them.
- Every string on screen comes from the scenario's language: the chrome in a
  small table per language, the domain words from the scenario's
  `display.labels`.

### What the display block gains

The viewer reads only the scenario's `display` block, as every other consumer
does. The mockup needed three things the block does not hold yet:

- **Labels for actor and place ids.** Labels cover resources, attributes and
  action types, not actors and places. The narrator puts the actor's English
  name in front of a Spanish predicate ("Third parties transferido…"), and the
  mockup needed its own table of Spanish place names. `display.labels` gains
  actor and place entries, and the narrator and the viewer both use them.
- **`display.card`**: which place attributes the place card shows.
- **`display.worse_when_higher`**: which of those the card colours red when
  they rise.

A scenario without them still plays: ids stand in for labels, and the card
shows no attribute bars.

## Testing

- **Server**: FastAPI's test client over every endpoint. The event stream test
  starts a run on `smoke` with a recorded engine, subscribes halfway, and
  requires the subscriber to receive every record in order, the early ones
  from the file and the rest live.
- **Streaming**: the incremental reader gets JSON fragments split at every
  possible position, and must emit exactly the rationale and nothing from the
  actions.
- **Observer**: a run with an observer writes a transcript byte-identical to
  the same run without one. The observer watches; it cannot change the run.
- **The viewer in a browser**: a headless Chromium steps a recorded bundle
  through every beat of every turn, hovers a place in each map, and fails on
  any console error or on a map drawn at zero size. This is the check that
  found three defects in the mockup that the code read as correct (chat text
  breaking into columns from a clashing class name, a recorded run frozen
  mid-resolution, a place card describing a state the screen had left). It
  runs in CI in its own job, with Playwright's Chromium. The existing
  `node --check` guard stays and runs on every script. The scripts are classic
  so that the bundle can concatenate them. That also keeps the guard honest:
  node 22 passes a `.js` file written in ES module syntax even with a syntax
  error, though it does fail an `.mjs` file.

## Order of work

Each slice ends in something Alex can open and use.

1. **The viewer over recordings.** The new `ui/`, the bundle's mutation
   counts, and `casus serve` with the shell and the read-only endpoints.
   Recorded runs play in four beats with the place card, on dots as today.
   No lingo change.
2. **Map regions** (`2026-09-29-map-regions-design.md`). The packaged map
   data, `casus regions`, computed adjacency, the class scenario migrated, and
   the viewer filling regions.
3. **Live runs.** The observer in `run_async`, `POST /api/runs`, the event
   stream. Beat 1 shows *thinking* until each declaration arrives.
4. **Streaming.** The lingo change, released; the incremental reader; `delta`
   messages; panes that type as the models write.
5. **Settings.** The screen, the config file, the probe, the leak test.
6. **Design mode** (`2026-09-29-design-mode-design.md`).
7. **Evaluate mode** (`2026-09-29-evaluate-mode-design.md`), with batches.

The labels gap is fixed in slice 1, because the viewer is the first thing that
shows it.

## Out of scope

- Accounts, remote access, several people at once. It is a local app.
- Editing the map by dragging places. Adjacency is edited as a list; the map
  only shows it.
- Streaming the models' hidden reasoning. lingo's `chat` already exposes
  `on_reasoning_token`, and showing it in beat 1 is a possible later step, but
  the rationale is what the player chose to say, and the teaching point is
  that the prose and the numbers come from different places.
- aegis, MCP, and an arbiter model, for the reasons the v2 design gives.

## Open questions

- Whether the war room should show fewer than five panes for scenarios with
  more actors, or scroll. The one scenario with a map has five.
