# Slice 1 — the viewer over recordings

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recorded runs play in the four-beat game viewer, in the app (`casus serve`) and in the offline bundle, with the place card on hover.

**Architecture:** `ui/js/*.js` are classic scripts on one `Casus` namespace. `records.js` folds transcript records into a `RunModel`; `viewer.js` plays a model in four beats; `map.js` and `card.js` draw the theatre and the hover card. `casus bundle` concatenates the scripts into `ui/bundle.html`; `casus serve` starts a FastAPI app that serves `ui/app.html`, the scripts, and three read-only endpoints.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, plain JS, pytest, Playwright (Python) with Chromium, node (for `node --check` and the JS unit harness).

**Specs:** `docs/specs/2026-09-28-interface-design.md` (all of "The shell", "The game viewer", "The frontend", "What the display block gains"). Master plan: `docs/plans/2026-09-29-casus-app-plan.md` (the contracts section is binding).

**Reference implementation of the look and the beat logic:** the mockup that was reviewed, `/home/apiad/Workspace/vault/Efforts/Areas/University/casus-clase/mockups/casus-v2.html`. It embeds a private scenario, so never copy data from it into the repo; copy CSS and logic only, as the tasks below say.

## Global Constraints

Everything in the master plan's Global Constraints, plus:

- The viewer computes nothing about the world. It draws records, and it may diff two recorded states.
- Pacing: live beats advance on a clock; recorded beats advance on the arrow key. `auto` (advance on your own) and `freeze` (stop the scene) are two separate controls.
- A scenario whose `display` block is empty still plays: ids stand in for labels, no ladder panel, no map panel when no place has `lat`/`lon`.

## Review Focus

Owned by this slice (from the master plan):

1. A transcript that ends mid-turn plays every complete turn and marks the incomplete one — `tests/browser/test_viewer.py::test_viewer_truncated_transcript`.
3. A scenario with an empty `display` block plays — `tests/browser/test_viewer.py::test_viewer_plays_a_scenario_with_an_empty_display_block`.

Also pinned here because this slice owns the code:

- A run id with path characters (`../x`) is a 404, never a file read outside `runs/` — `tests/test_server.py::test_a_run_id_cannot_leave_the_runs_directory`.
- A map redrawn under a still pointer refreshes the card — `tests/browser/test_viewer.py::test_card_refreshes_when_the_map_redraws`.
- A recorded run's resolution animation plays while auto-advance is off — `tests/browser/test_viewer.py::test_recorded_resolution_is_not_frozen`.

---

### Task 1: Labels and card settings in the display block

**Files:**
- Modify: `src/casus/display.py`
- Modify: `src/casus/narrator.py:84-93`
- Modify: `scenarios/smoke/scenario.yaml` (display block)
- Modify: `scenarios/reference/scenario.yaml` (display block)
- Test: `tests/test_display.py`, `tests/test_narrator.py`

**Interfaces:**
- Produces: `display.actor_label(scenario, actor_id) -> str`, `display.place_label(scenario, place_id) -> str`, `display.card(scenario) -> tuple[str, ...]`, `display.worse_when_higher(scenario) -> frozenset[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_display.py`:

```python
from casus import display


def _with_display(smoke_data, **block):
    from casus.scenario import Scenario

    data = {**smoke_data, "display": {**smoke_data.get("display", {}), **block}}
    return Scenario.from_parts(data, SMOKE_RULES)


def test_an_actor_label_comes_from_the_scenario_language(smoke_data):
    scenario = _with_display(
        {**smoke_data, "language": "es"}, labels={"es": {"BLUE": "Azules"}}
    )
    assert display.actor_label(scenario, "BLUE") == "Azules"


def test_an_actor_without_a_label_falls_back_to_its_name(smoke_data):
    scenario = _with_display(smoke_data, labels={})
    assert display.actor_label(scenario, "RED") == smoke_data["actors"]["RED"]["name"]


def test_a_place_label_falls_back_to_its_name_then_its_id(smoke_data):
    scenario = _with_display(smoke_data, labels={})
    assert display.place_label(scenario, "border") == smoke_data["places"]["border"]["name"]
    assert display.place_label(scenario, "nowhere") == "nowhere"


def test_card_and_worse_when_higher_default_to_empty(smoke_data):
    scenario = _with_display(smoke_data)
    assert display.card(scenario) == ()
    assert display.worse_when_higher(scenario) == frozenset()


def test_card_and_worse_when_higher_read_the_block(smoke_data):
    scenario = _with_display(smoke_data, card=["infra"], worse_when_higher=["infra"])
    assert display.card(scenario) == ("infra",)
    assert display.worse_when_higher(scenario) == frozenset({"infra"})
```

If `tests/test_display.py` has no `smoke_data` fixture and `SMOKE_RULES` constant, add them at the top of the file:

```python
import pathlib

import pytest
import yaml

SMOKE = pathlib.Path(__file__).parent.parent / "scenarios" / "smoke"
SMOKE_RULES = (SMOKE / "rules.py").read_text()


@pytest.fixture
def smoke_data() -> dict:
    return yaml.safe_load((SMOKE / "scenario.yaml").read_text())
```

Append to `tests/test_narrator.py`:

```python
def test_the_subject_is_the_actor_label_in_the_scenario_language():
    """The narrator wrote 'Third parties transferido…' because it used the
    actor's English name in front of a Spanish predicate."""
    import asyncio

    from casus import display, narrator
    from casus.state import Event

    scenario, world = _spanish_scenario_with_label("BLUE", "Azules")
    fact = Event(id="resupplied", detail={"actor": "BLUE", "reason": "sent supplies"})
    engine = _engine_replying(["enviaron suministros"])
    text = asyncio.run(narrator.narrate(world, [fact], engine, scenario))
    assert text.startswith(display.actor_label(scenario, "BLUE") + " ")
```

Add the two helpers next to the existing ones in `tests/test_narrator.py` (read the top of the file first; reuse its existing scenario builder if one takes a language):

```python
def _spanish_scenario_with_label(actor_id: str, label: str):
    import pathlib

    import yaml

    from casus.scenario import Scenario

    smoke = pathlib.Path(__file__).parent.parent / "scenarios" / "smoke"
    data = yaml.safe_load((smoke / "scenario.yaml").read_text())
    data["language"] = "es"
    data["display"] = {**data.get("display", {}), "labels": {"es": {actor_id: label}}}
    scenario = Scenario.from_parts(data, (smoke / "rules.py").read_text())
    return scenario, scenario.initial_state()


def _engine_replying(predicates: list[str]):
    from helpers import FakeEngine

    return FakeEngine({"predicates": predicates})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_display.py tests/test_narrator.py -q`
Expected: FAIL with `AttributeError: module 'casus.display' has no attribute 'actor_label'`.

- [ ] **Step 3: Implement**

Append to `src/casus/display.py`:

```python
def _labels(scenario: Scenario) -> dict[str, str]:
    return (scenario.display.get("labels") or {}).get(scenario.language()) or {}


def actor_label(scenario: Scenario, actor_id: str) -> str:
    """What the room reads for an actor: the label in the scenario's language,
    else the actor's name, else its id."""
    labelled = _labels(scenario).get(actor_id)
    if labelled:
        return str(labelled)
    return str((scenario.data["actors"].get(actor_id) or {}).get("name") or actor_id)


def place_label(scenario: Scenario, place_id: str) -> str:
    labelled = _labels(scenario).get(place_id)
    if labelled:
        return str(labelled)
    return str((scenario.data["places"].get(place_id) or {}).get("name") or place_id)


def card(scenario: Scenario) -> tuple[str, ...]:
    """The place attributes the place card shows, in order."""
    return tuple(scenario.display.get("card") or ())


def worse_when_higher(scenario: Scenario) -> frozenset[str]:
    """Attributes whose rise is bad for the place, so the card colours it red."""
    return frozenset(scenario.display.get("worse_when_higher") or ())
```

In `src/casus/narrator.py`, replace the `names = {a.id: a.name for a in world.actors.values()}` line and the `subject = names.get(...)` line inside `narrate` with:

```python
    lines = []
    for fact, predicate in zip(facts, dispatch.predicates, strict=True):
        text = " ".join(str(predicate).split())
        if not text:
            continue
        actor = fact.detail.get("actor") or ""
        subject = display.actor_label(scenario, actor) if actor in world.actors else ""
        sentence = f"{subject} {text}".strip() if subject else text
        lines.append(sentence if sentence.endswith((".", "!", "?")) else sentence + ".")
    return " ".join(lines)
```

(`display` is already imported in `narrator.py`; check with `grep -n "^from\|^import" src/casus/narrator.py`.)

In `scenarios/smoke/scenario.yaml`, extend the `display` block:

```yaml
  card: [infra]
  worse_when_higher: []
```

and add actor and place labels to the existing `es` labels:

```yaml
  labels:
    es: {stamina: aguante, supplies: suministros, BLUE: Azules, RED: Rojos,
         b-home: Base azul, border: La frontera, r-home: Base roja}
```

In `scenarios/reference/scenario.yaml`, add under `display`:

```yaml
  card: [control, infrastructure, civilian_distress]
  worse_when_higher: [civilian_distress]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_display.py tests/test_narrator.py tests/test_scenario.py -q`
Expected: PASS.

- [ ] **Step 5: Migrate the private class scenario (outside this repo)**

The Caribbean scenario lives in the private vault through `scenarios/private`. Add to its `display` block, in `/home/apiad/Workspace/vault/Efforts/Areas/University/casus-clase/caribbean-2026/scenario.yaml`:

```yaml
  card: [control, infrastructure, civilian_distress]
  worse_when_higher: [civilian_distress]
```

and to `display.labels.es` the actor and place ids:

```yaml
      US: EE.UU.
      CU: Cuba
      RU: Rusia
      CN: China
      THIRD: Terceros
      cu-habana: La Habana
      cu-occidente: Occidente
      cu-centro: Centro
      cu-oriente: Oriente
      gtmo: Guantánamo
      us-florida: Sur de Florida
      str-florida: Estrecho de Florida
      car-north: Caribe norte
```

Run `uv run casus validate scenarios/private/caribbean-2026` and expect no findings. Commit that file in the Workspace repo, not here: `git -C /home/apiad/Workspace add vault/Efforts/Areas/University/casus-clase/caribbean-2026/scenario.yaml && git -C /home/apiad/Workspace commit -m "feat(casus-clase): actor and place labels, place card settings"`.

- [ ] **Step 6: Commit**

```bash
git add src/casus/display.py src/casus/narrator.py scenarios/smoke/scenario.yaml \
  scenarios/reference/scenario.yaml tests/test_display.py tests/test_narrator.py
git commit -m "feat(display): actor and place labels, place card settings"
```

---

### Task 2: Runs on disk

**Files:**
- Create: `src/casus/studies.py`
- Test: `tests/test_studies.py`

**Interfaces:**
- Consumes: `engine.read_records(path) -> list[dict]` (exists).
- Produces: `RunInfo` and `list_runs(runs_dir) -> list[RunInfo]` exactly as in the master plan.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_studies.py`:

```python
import json
import pathlib

from casus import engine, studies
from casus.scenario import Scenario
from helpers import FakeEngine

SMOKE = pathlib.Path(__file__).parent.parent / "scenarios" / "smoke"


def _run(runs_dir: pathlib.Path, seed: int, turns: int = 2) -> pathlib.Path:
    scenario = Scenario.load(SMOKE)
    out = runs_dir / f"smoke-{seed}.jsonl"
    engines = {a: FakeEngine() for a in scenario.actors}
    engine.run(scenario, seed=seed, out=out, engines=engines, turns=turns)
    return out


def test_a_complete_run_is_listed_with_its_seed_and_turns(tmp_path):
    _run(tmp_path, seed=7, turns=2)
    [info] = studies.list_runs(tmp_path)
    assert (info.id, info.scenario, info.seed) == ("smoke-7", "smoke", 7)
    assert (info.turns_planned, info.turns_done, info.status) == (2, 2, "complete")


def test_a_transcript_cut_mid_turn_is_incomplete(tmp_path):
    path = _run(tmp_path, seed=3, turns=2)
    lines = path.read_text().splitlines()
    last_state = max(i for i, line in enumerate(lines) if json.loads(line)["kind"] == "state")
    path.write_text("\n".join(lines[: last_state - 1]) + "\n")
    [info] = studies.list_runs(tmp_path)
    assert info.status == "incomplete"
    assert info.turns_done == 1


def test_a_run_that_recorded_an_error_is_failed(tmp_path):
    path = _run(tmp_path, seed=4, turns=1)
    with path.open("a") as fh:
        fh.write(json.dumps({"kind": "error", "turn": 2, "error": "boom"}) + "\n")
    [info] = studies.list_runs(tmp_path)
    assert info.status == "failed"


def test_files_that_are_not_transcripts_are_skipped(tmp_path):
    _run(tmp_path, seed=1)
    (tmp_path / "notes.jsonl").write_text("not json\n")
    (tmp_path / "empty.jsonl").write_text("")
    assert [i.id for i in studies.list_runs(tmp_path)] == ["smoke-1"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_studies.py -q`
Expected: FAIL with `ImportError: cannot import name 'studies'`.

- [ ] **Step 3: Implement**

Create `src/casus/studies.py`:

```python
"""What is on disk under runs/: which transcripts exist and how far each got.

A run's id is its file stem. Reading a run's header costs one line; counting
its turns costs a pass over the file, which is fine for a class's worth of runs.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Literal

Status = Literal["complete", "failed", "incomplete"]


@dataclasses.dataclass(frozen=True)
class RunInfo:
    id: str
    path: pathlib.Path
    scenario: str
    seed: int
    turns_planned: int
    turns_done: int
    status: Status

    def to_json(self) -> dict:
        return {**dataclasses.asdict(self), "path": str(self.path)}


def _scan(path: pathlib.Path) -> RunInfo | None:
    header, states, failed, ended = None, 0, False, False
    try:
        with path.open() as fh:
            for line in fh:
                if not line.strip():
                    continue
                record = json.loads(line)
                kind = record.get("kind")
                if header is None:
                    if kind != "scenario":
                        return None
                    header = record
                elif kind == "state":
                    states += 1
                elif kind == "error":
                    failed = True
                elif kind == "end":
                    ended = True
    except (OSError, json.JSONDecodeError):
        return None
    if header is None:
        return None
    status: Status = "failed" if failed else "complete" if ended else "incomplete"
    return RunInfo(
        id=path.stem,
        path=path,
        scenario=str(header.get("name", "")),
        seed=int(header.get("seed", 0)),
        turns_planned=int(header.get("turns", 0)),
        turns_done=max(states - 1, 0),
        status=status,
    )


def list_runs(runs_dir: pathlib.Path) -> list[RunInfo]:
    """Every readable transcript directly under `runs_dir`, sorted by id."""
    if not runs_dir.is_dir():
        return []
    found = (_scan(p) for p in sorted(runs_dir.glob("*.jsonl")))
    return [info for info in found if info is not None]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_studies.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/casus/studies.py tests/test_studies.py
git commit -m "feat(studies): list the runs on disk and how far each got"
```

---

### Task 3: Records for the viewer

**Files:**
- Modify: `src/casus/bundle.py`
- Test: `tests/test_bundle.py`

**Interfaces:**
- Produces: `bundle.viewer_records(records: list[dict]) -> list[dict]`, `bundle.KEPT_KINDS` now includes `"error"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bundle.py`:

```python
def test_viewer_records_count_each_turns_mutations_in_one_ledger_record(transcript):
    records = engine.read_records(transcript)
    counted = {}
    for r in records:
        if r["kind"] == "mutation":
            counted[r["turn"]] = counted.get(r["turn"], 0) + 1
    kept = bundle.viewer_records(records)
    ledgers = {r["turn"]: r["mutations"] for r in kept if r["kind"] == "ledger"}
    assert ledgers == counted
    assert not any(r["kind"] in ("mutation", "declaration") for r in kept)


def test_a_ledger_record_sits_before_the_state_that_closes_its_turn(transcript):
    kept = bundle.viewer_records(engine.read_records(transcript))
    for i, r in enumerate(kept):
        if r["kind"] == "ledger":
            following = next(x for x in kept[i + 1 :] if x["kind"] == "state")
            assert following["turn"] == r["turn"] + 1


def test_an_error_record_reaches_the_viewer():
    records = [
        {"kind": "scenario", "turn": 0, "name": "x", "scenario": {}},
        {"kind": "error", "turn": 1, "error": "rule raised"},
    ]
    assert bundle.viewer_records(records)[-1]["kind"] == "error"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_bundle.py -q -k "viewer_records or ledger_record or error_record"`
Expected: FAIL with `AttributeError: module 'casus.bundle' has no attribute 'viewer_records'`.

- [ ] **Step 3: Implement**

In `src/casus/bundle.py`, change `KEPT_KINDS` and add `viewer_records`:

```python
#: Record kinds the viewer reads. `declaration` records are the replay payload and
#: `mutation` records are the ledger; both stay in the transcript for audit. The
#: `action` records already carry the rationale and the assessment, and the one
#: thing the viewer needs from the ledger, a count per turn, travels as a small
#: `ledger` record written here.
KEPT_KINDS = frozenset(
    {"scenario", "state", "action", "event", "narrative", "prompt", "end", "error"}
)


def viewer_records(records: list[dict]) -> list[dict]:
    """The records the viewer plays, with each turn's mutations replaced by a
    count placed just before the state that closes that turn."""
    counts: dict[int, int] = {}
    for r in records:
        if r["kind"] == "mutation":
            counts[r["turn"]] = counts.get(r["turn"], 0) + 1
    out: list[dict] = []
    for r in records:
        if r["kind"] == "state" and (r["turn"] - 1) in counts:
            out.append({"kind": "ledger", "turn": r["turn"] - 1, "mutations": counts.pop(r["turn"] - 1)})
        if r["kind"] in KEPT_KINDS:
            out.append(r)
    for turn, n in sorted(counts.items()):
        out.append({"kind": "ledger", "turn": turn, "mutations": n})
    return out
```

Replace `kept = [r for r in records if r["kind"] in KEPT_KINDS]` in `bundle()` with `kept = viewer_records(records)`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_bundle.py -q`
Expected: PASS, including the existing `test_the_ledger_stays_in_the_transcript_and_out_of_the_bundle`.

- [ ] **Step 5: Commit**

```bash
git add src/casus/bundle.py tests/test_bundle.py
git commit -m "feat(bundle): viewer records, with a mutation count per turn"
```

---

### Task 4: The run model and the chrome strings (`records.js`, `i18n.js`)

**Files:**
- Create: `ui/js/i18n.js`, `ui/js/records.js`
- Create: `tests/js/harness.js`
- Test: `tests/test_ui_scripts.py`

**Interfaces:**
- Produces: `Casus.i18n.use(lang)`, `Casus.i18n.t(key)`, `Casus.records.RunModel` with `.push(record)`, `.onChange(fn)`, `.scenario`, `.header`, `.turns`, `.turn(n)`, `.playable()`, `.deltas`, `.error`, `.ended`, and the helpers `Casus.records.actorIds(run)`, `Casus.records.label(run, key)`, `Casus.records.declarations(turn)`.

The JS unit tests run the scripts under node with a fake `window`, so they need no browser.

- [ ] **Step 1: Write the harness and the failing test**

Create `tests/js/harness.js`:

```js
// Loads ui/js scripts into one context with a fake window, then runs the test
// named on the command line. Prints JSON; exits 1 on a failed assertion.
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const root = path.join(__dirname, "..", "..", "ui", "js");
const ctx = { window: {}, console };
ctx.window.window = ctx.window;
vm.createContext(ctx);
for (const name of process.argv[2].split(",")) {
  vm.runInContext(fs.readFileSync(path.join(root, name), "utf8"), ctx, { filename: name });
}
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const Casus = ctx.window.Casus;
const run = new Casus.records.RunModel();
for (const r of input.records) run.push(r);
const out = {
  scenario: run.header && run.header.name,
  playable: run.playable().map((t) => t.turn),
  complete: run.playable().map((t) => t.complete),
  mutations: run.playable().map((t) => t.mutations),
  actors: Casus.records.actorIds(run),
  labels: input.labels.map((k) => Casus.records.label(run, k)),
  declared: run.playable().map((t) => Casus.records.declarations(t).map((d) => d.actor)),
  error: run.error && run.error.error,
  ended: run.ended,
};
process.stdout.write(JSON.stringify(out));
```

Create `tests/test_ui_scripts.py`:

```python
"""The viewer's data layer, run under node without a browser."""

import json
import pathlib
import shutil
import subprocess

import pytest

from casus import bundle, engine
from casus.scenario import Scenario
from helpers import FakeEngine

ROOT = pathlib.Path(__file__).parent.parent
HARNESS = ROOT / "tests" / "js" / "harness.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _records(tmp_path, turns=2):
    scenario = Scenario.load(ROOT / "scenarios" / "smoke")
    out = tmp_path / "run.jsonl"
    engines = {a: FakeEngine() for a in scenario.actors}
    engine.run(scenario, seed=1, out=out, engines=engines, turns=turns)
    return bundle.viewer_records(engine.read_records(out))


def _model(records, labels=()):
    payload = json.dumps({"records": records, "labels": list(labels)})
    done = subprocess.run(
        [NODE, str(HARNESS), "i18n.js,records.js"],
        input=payload, capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_complete_run_folds_into_its_playable_turns(tmp_path):
    records = _records(tmp_path, turns=2)
    model = _model(records)
    assert model["scenario"] == "smoke"
    assert model["playable"] == [1, 2]
    assert model["complete"] == [True, True]
    assert model["ended"] is True
    assert model["actors"] == ["BLUE", "RED"]
    assert model["declared"] == [["BLUE", "RED"], ["BLUE", "RED"]]


def test_mutation_counts_come_from_the_ledger_records(tmp_path):
    records = _records(tmp_path, turns=2)
    expected = [r["mutations"] for r in records if r["kind"] == "ledger"]
    assert _model(records)["mutations"] == expected


def test_a_run_cut_before_its_last_state_leaves_that_turn_incomplete(tmp_path):
    records = _records(tmp_path, turns=2)
    last_state = max(i for i, r in enumerate(records) if r["kind"] == "state")
    model = _model(records[:last_state])
    assert model["complete"] == [True, False]
    assert model["ended"] is False


def test_labels_fall_back_from_display_to_names_to_ids(tmp_path):
    model = _model(_records(tmp_path), labels=["BLUE", "border", "no_such_thing"])
    assert model["labels"] == ["Blue", "The Border", "no such thing"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ui_scripts.py -q`
Expected: FAIL (node cannot read `ui/js/i18n.js`).

- [ ] **Step 3: Implement `ui/js/i18n.js`**

```js
// Chrome strings. Domain words never live here: they come from the scenario's
// display.labels, through Casus.records.label.
(function () {
  const C = (window.Casus = window.Casus || {});
  const STRINGS = {
    en: {
      thinking: "thinking", declaring: "declaring", resolving: "resolving", dispatch: "dispatch",
      writing: "writing…", ready: "declaration ready", sealed: "DECLARATION SEALED",
      ready_count: "ready", declared_count: "declared", mutations: "mutations",
      ledger: "mutations in the ledger", day: "DAY", live: "LIVE", recorded: "RECORDED",
      frozen: "FROZEN", auto_on: "❚❚ manual", auto_off: "▶ advance on its own",
      keys: "→ next beat · ← previous · space freeze · P present · Esc leave",
      theatre: "Theatre", aimed: "Theatre · declared targets", ladder: "Ladder · highest rung",
      standing: "Standing", expects: "Expects of the other side:", dispatch_of: "Dispatch of day",
      no_dispatch: "No dispatch this day.", incomplete: "This turn did not finish.",
      failed: "The run stopped here:", end: "END", home: "Home", scenarios: "Scenarios",
      studies: "Runs", view: "View", no_map: "no map for this scenario",
      at_start: "at the start of day", after: "after resolving day", initial: "initial state",
      forces_here: "Forces here", no_forces: "no forces here", aimed_here: "Declared against this place · day",
      nobody_aimed: "nobody declared anything against this place",
      still_sealed: "the declarations are still sealed", borders: "Borders", source: "source",
      controlled_by: "held by", open_water: "nobody holds it", arrived: "arrived from", left: "left",
    },
    es: {
      thinking: "pensando", declaring: "declarando", resolving: "resolviendo", dispatch: "parte",
      writing: "escribiendo…", ready: "declaración lista", sealed: "DECLARACIÓN SELLADA",
      ready_count: "listos", declared_count: "declarados", mutations: "mutaciones",
      ledger: "mutaciones en el libro mayor", day: "DÍA", live: "EN VIVO", recorded: "GRABADA",
      frozen: "CONGELADO", auto_on: "❚❚ manual", auto_off: "▶ avanzar solo",
      keys: "→ siguiente compás · ← anterior · espacio congelar · P presentar · Esc salir",
      theatre: "Teatro", aimed: "Teatro · objetivos declarados", ladder: "Escalera · peldaño más alto",
      standing: "Situación", expects: "Espera del rival:", dispatch_of: "Parte del día",
      no_dispatch: "Sin parte este día.", incomplete: "Este turno no terminó.",
      failed: "La corrida se detuvo aquí:", end: "FIN", home: "Inicio", scenarios: "Escenarios",
      studies: "Partidas", view: "Ver", no_map: "este escenario no tiene mapa",
      at_start: "al empezar el día", after: "tras resolver el día", initial: "estado inicial",
      forces_here: "Fuerzas aquí", no_forces: "ninguna fuerza aquí", aimed_here: "Declarado para aquí · día",
      nobody_aimed: "nadie declaró nada contra este lugar",
      still_sealed: "las declaraciones siguen selladas", borders: "Linda con", source: "fuente",
      controlled_by: "controla", open_water: "aguas abiertas", arrived: "llega de", left: "se fue",
    },
  };
  let lang = "en";
  C.i18n = {
    use(l) { lang = STRINGS[l] ? l : "en"; },
    lang() { return lang; },
    t(key) { return (STRINGS[lang] && STRINGS[lang][key]) || STRINGS.en[key] || key; },
  };
})();
```

- [ ] **Step 4: Implement `ui/js/records.js`**

```js
// Folds transcript records into turns. State N is the world before turn N
// resolves, so turn N's `after` is state N+1 and a turn is complete when that
// state exists. Records may arrive all at once (a bundle) or one by one (live).
(function () {
  const C = (window.Casus = window.Casus || {});

  function emptyTurn(n) {
    return { turn: n, before: null, after: null, prompts: [], actions: [], events: [],
             narrative: "", mutations: 0, complete: false };
  }

  class RunModel {
    constructor() {
      this.header = null; this.scenario = {}; this.turns = []; this.deltas = {};
      this.error = null; this.ended = false; this._fns = [];
    }
    onChange(fn) { this._fns.push(fn); }
    turn(n) { return this.turns.find((t) => t.turn === n) || null; }
    _ensure(n) {
      let t = this.turn(n);
      if (!t) { t = emptyTurn(n); this.turns.push(t); this.turns.sort((a, b) => a.turn - b.turn); }
      return t;
    }
    push(r) {
      switch (r.kind) {
        case "scenario": this.header = r; this.scenario = r.scenario || {}; break;
        case "state": {
          this._ensure(r.turn).before = r.state;
          const prev = this.turn(r.turn - 1);
          if (prev) { prev.after = r.state; prev.complete = true; }
          break;
        }
        case "prompt": this._ensure(r.turn).prompts.push(r); break;
        case "action": this._ensure(r.turn).actions.push(r); break;
        case "event": this._ensure(r.turn).events.push(r.event); break;
        case "ledger": this._ensure(r.turn).mutations = r.mutations; break;
        case "mutation": this._ensure(r.turn).mutations += 1; break;
        case "narrative": this._ensure(r.turn).narrative = r.text || ""; break;
        case "delta": {
          const byActor = (this.deltas[r.turn] = this.deltas[r.turn] || {});
          (byActor[r.actor] = byActor[r.actor] || []).push(r.text);
          break;
        }
        case "error": this.error = r; break;
        case "end": this.ended = true; break;
        default: return;
      }
      for (const fn of this._fns) fn(r.kind, this, r);
    }
    // Turns somebody was asked about. The last state opens a turn nobody plays.
    playable() { return this.turns.filter((t) => t.prompts.length || t.actions.length); }
  }

  function actorIds(run) { return Object.keys(run.scenario.actors || {}).sort(); }

  function label(run, key) {
    const d = run.scenario.display || {};
    const lang = (run.header && run.header.language) || run.scenario.language || "en";
    const labels = (d.labels || {})[lang] || {};
    if (labels[key]) return String(labels[key]);
    const a = (run.scenario.actors || {})[key];
    if (a && a.name) return String(a.name);
    const p = (run.scenario.places || {})[key];
    if (p && p.name) return String(p.name);
    return String(key).replace(/_/g, " ");
  }

  // One entry per actor that declared, in actor order: its actions, and the
  // rationale and assessment the action records all repeat.
  function declarations(turn) {
    const by = {};
    for (const r of turn.actions) {
      const d = (by[r.actor] = by[r.actor] || { actor: r.actor, actions: [], rationale: "", assessment: "" });
      d.actions.push(r.action);
      d.rationale = d.rationale || r.rationale || "";
      d.assessment = d.assessment || r.assessment || "";
    }
    return Object.keys(by).sort().map((k) => by[k]);
  }

  C.records = { RunModel, actorIds, label, declarations };
})();
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_ui_scripts.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add ui/js/i18n.js ui/js/records.js tests/js/harness.js tests/test_ui_scripts.py
git commit -m "feat(ui): the run model and the chrome strings"
```

---

### Task 5: The map (dots) and the place card (`map.js`, `card.js`, `app.css`)

**Files:**
- Create: `ui/js/map.js`, `ui/js/card.js`, `ui/css/app.css`
- Test: `tests/test_ui_scripts.py` (card content under node)

**Interfaces:**
- Consumes: `Casus.records.label`, `Casus.i18n.t`.
- Produces: `Casus.map.draw(svg, run, snapshot, opts) -> void`, `Casus.map.hasMap(run) -> bool`, `Casus.map.colour(run, actorId) -> string`, `Casus.card.html(run, placeId, ctx) -> string`, `Casus.card.attach(documentRoot)`, `Casus.card.refresh()`.
- `opts` for `draw`: `{targets: [{actor, place}], font: number, aspect: number, slice: bool, edges: bool, rscale: number, ctx: {turn, prev, actions, sealed}}`. When `opts.ctx` is present the places are hover targets for the card.
- The world outline comes from `window.CASUS_WORLDMAP` (the parsed `ui/worldmap.json`), set by the page before the scripts run.

- [ ] **Step 1: Write the failing card test**

Add to `tests/js/harness.js`, after `const out = {...}` and before `process.stdout.write`, a card rendering when `input.card` is given:

```js
if (input.card) {
  const t = run.playable()[0];
  out.card = Casus.card.html(run, input.card, {
    snapshot: t.after || t.before, prev: t.after ? t.before : null, turn: t.turn,
    actions: Casus.records.declarations(t), sealed: !!input.sealed,
  });
}
```

Append to `tests/test_ui_scripts.py`:

```python
def _card(records, place, sealed=False):
    payload = json.dumps({"records": records, "labels": [], "card": place, "sealed": sealed})
    done = subprocess.run(
        [NODE, str(HARNESS), "i18n.js,records.js,map.js,card.js"],
        input=payload, capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["card"]


def test_the_card_names_the_place_its_holder_and_its_neighbours(tmp_path):
    html = _card(_records(tmp_path), "border")
    assert "The Border" in html
    assert "Red" in html
    assert "Blue Home" in html and "Red Home" in html


def test_a_sealed_turn_does_not_reveal_what_was_aimed_at_the_place(tmp_path):
    html = _card(_records(tmp_path), "border", sealed=True)
    assert "the declarations are still sealed" in html


def test_the_card_shows_before_and_after_for_card_attributes(tmp_path):
    html = _card(_records(tmp_path), "border")
    assert "infra" in html
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ui_scripts.py -q -k card`
Expected: FAIL (no `map.js`).

- [ ] **Step 3: Implement `ui/js/map.js`**

```js
// The theatre. Slice 1 draws dots from each place's lat/lon over the world
// outline; slice 2 adds filled regions when the scenario record carries them.
(function () {
  const C = (window.Casus = window.Casus || {});
  const PALETTE = ["#4fa3ff", "#ff5a6e", "#a98bff", "#f5c451", "#4fd1b5", "#ff9e5e", "#7ee081", "#e07ee0"];
  const CTX = {}; let seq = 0;

  function colour(run, actorId) {
    const i = C.records.actorIds(run).indexOf(actorId);
    return i < 0 ? "#8a95a5" : PALETTE[i % PALETTE.length];
  }
  function places(run) { return run.scenario.places || {}; }
  function coords(p) {
    const a = p.attrs || {};
    return typeof a.lat === "number" && typeof a.lon === "number" ? [a.lon, a.lat] : null;
  }
  function hasMap(run) { return Object.values(places(run)).some((p) => coords(p)); }

  function world() { return window.CASUS_WORLDMAP || { projection: { width: 1000, height: 500 }, countries: {} }; }
  function px(lon) { return ((lon + 180) / 360) * world().projection.width; }
  function py(lat) { return ((90 - lat) / 180) * world().projection.height; }

  function box(run, aspect) {
    const pts = Object.values(places(run)).map(coords).filter(Boolean);
    const xs = pts.map((c) => px(c[0])), ys = pts.map((c) => py(c[1]));
    let x0 = Math.min(...xs) - 7, x1 = Math.max(...xs) + 7, y0 = Math.min(...ys) - 6, y1 = Math.max(...ys) + 6;
    let w = x1 - x0, h = y1 - y0;
    if (w / h < aspect) { const nw = h * aspect; x0 -= (nw - w) / 2; w = nw; }
    else { const nh = w / aspect; y0 -= (nh - h) / 2; h = nh; }
    return { x: x0, y: y0, w, h };
  }

  function strengthAt(run, snap, placeId) {
    const size = ((run.scenario.display || {}).map || {}).size || "strength";
    return (snap.entities || []).filter((e) => e.place === placeId)
      .reduce((s, e) => s + Number((e.attrs || {})[size] || 0), 0);
  }

  function draw(svg, run, snap, opts) {
    opts = opts || {};
    if (!hasMap(run)) { svg.outerHTML = `<div class="nomap">${C.i18n.t("no_map")}</div>`; return; }
    const b = box(run, opts.aspect || 2), S = b.w / 100;
    const ring = ((run.scenario.display || {}).map || {}).ring;
    const cid = opts.ctx ? ++seq : 0;
    if (cid) CTX[cid] = Object.assign({ snapshot: snap }, opts.ctx);
    let o = "";
    for (const [iso, d] of Object.entries(world().countries || {})) {
      o += `<path class="land" d="${d}" stroke-width="${(0.12 * S).toFixed(3)}"/>`;
    }
    if (opts.edges) {
      const seen = new Set();
      for (const [id, p] of Object.entries(places(run))) {
        for (const q of p.adjacency || []) {
          const k = [id, q].sort().join("|"), r = places(run)[q];
          if (seen.has(k) || !r || !coords(p) || !coords(r)) continue; seen.add(k);
          const a = coords(p), c = coords(r);
          o += `<line class="edge" x1="${px(a[0])}" y1="${py(a[1])}" x2="${px(c[0])}" y2="${py(c[1])}" stroke-width="${0.18 * S}" stroke-dasharray="${0.6 * S} ${0.6 * S}"/>`;
        }
      }
    }
    let i = 0;
    for (const [id, p] of Object.entries(places(run))) {
      const c = coords(p); if (!c) continue;
      const x = px(c[0]), y = py(c[1]);
      const st = (snap.places || {})[id] || { owner: p.owner, attrs: p.attrs || {} };
      const r = (0.8 + Math.sqrt(Math.max(strengthAt(run, snap, id), 0)) * 0.28) * S * (opts.rscale || 1);
      const fill = st.owner ? colour(run, st.owner) : "#5a626c";
      if (cid) o += `<g class="pl" data-place="${id}">`;
      const v = ring ? Number((st.attrs || {})[ring] || 0) : 0;
      if (v > 0) {
        const rr = r + 0.9 * S, circ = 2 * Math.PI * rr;
        o += `<circle cx="${x}" cy="${y}" r="${rr}" fill="none" stroke="#ff8a9b" stroke-width="${0.35 * S}" stroke-dasharray="${(Math.min(v, 100) / 100) * circ} ${circ}" transform="rotate(-90 ${x} ${y})"/>`;
      }
      for (const t of (opts.targets || []).filter((t) => t.place === id)) {
        o += `<circle class="target" cx="${x}" cy="${y}" r="${r + 1.4 * S}" stroke="${colour(run, t.actor)}" stroke-width="${0.4 * S}"/>`;
      }
      o += `<circle class="mk" cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke-width="${0.25 * S}"/>`;
      const flip = i++ % 2 === 1, fs = (opts.font || 1.9) * S;
      if (fs > 0) {
        o += `<text class="plabel" x="${flip ? x - r - S : x + r + S}" y="${y + fs * 0.35}" text-anchor="${flip ? "end" : "start"}" font-size="${fs}" stroke-width="${0.35 * S}">${esc(C.records.label(run, id))}</text>`;
      }
      if (cid) o += `<circle cx="${x}" cy="${y}" r="${r + 2.2 * S}" fill="transparent"/></g>`;
    }
    svg.setAttribute("viewBox", `${b.x} ${b.y} ${b.w} ${b.h}`);
    svg.setAttribute("preserveAspectRatio", `xMidYMid ${opts.slice ? "slice" : "meet"}`);
    if (cid) svg.dataset.ctx = String(cid); else delete svg.dataset.ctx;
    svg.innerHTML = o;
  }

  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }

  C.map = { draw, hasMap, colour, esc, context: (id) => CTX[id] || null };
})();
```

- [ ] **Step 4: Implement `ui/js/card.js`**

```js
// The place card: what a place is, who holds it, what is there, what was aimed
// at it, and what changed. It reads the context the map stored when it drew.
(function () {
  const C = (window.Casus = window.Casus || {});
  const t = (k) => C.i18n.t(k);

  function fmt(v) {
    const n = Number(v);
    if (!isFinite(n)) return String(v);
    const s = Math.abs(n) >= 10 || Number.isInteger(n) ? String(Math.round(n)) : n.toFixed(1);
    return C.i18n.lang() === "es" ? s.replace(".", ",") : s;
  }
  function value(a, b, worse) {
    if (b === undefined || Math.abs(b - a) < 0.05) return `<span class="tv">${fmt(a)}</span>`;
    const bad = (b < a) !== !!worse;
    return `<span class="tv ${bad ? "down" : "up"}">${fmt(a)} → ${fmt(b)}</span>`;
  }

  function html(run, placeId, c) {
    const esc = C.map.esc, L = (k) => esc(C.records.label(run, k));
    const d = run.scenario.display || {}, p = (run.scenario.places || {})[placeId] || {};
    const st = (c.snapshot.places || {})[placeId] || { owner: p.owner, attrs: p.attrs || {} };
    const pv = c.prev ? (c.prev.places || {})[placeId] : null;
    const worse = new Set(d.worse_when_higher || []);
    const attrs = (d.card || []).map((k) => {
      const now = Number((st.attrs || {})[k] || 0);
      const was = pv ? Number((pv.attrs || {})[k] || 0) : undefined;
      const max = ((run.scenario.attributes || {})[k] || {}).max || 100;
      const col = worse.has(k) ? "#ff8a9b" : st.owner ? C.map.colour(run, st.owner) : "#8a95a5";
      return `<div class="trow"><span>${L(k)}</span><div class="bar"><i style="width:${Math.min(100, (now / max) * 100)}%;background:${col}"></i></div>${was === undefined ? value(now) : value(was, now, worse.has(k))}</div>`;
    }).join("");
    const size = (d.map || {}).size || "strength";
    const prevE = {}; for (const e of (c.prev ? c.prev.entities : []) || []) prevE[e.id] = e;
    const here = (c.snapshot.entities || []).filter((e) => e.place === placeId);
    const gone = c.prev ? (c.prev.entities || []).filter((e) => e.place === placeId && !here.some((h) => h.id === e.id)) : [];
    const force = (e, note, v) => `<div class="frow"><i style="background:${C.map.colour(run, e.owner)}"></i><span>${L(e.kind)}</span><span class="fid">${esc(e.id)}${note}</span>${v}</div>`;
    const forces = here.length || gone.length
      ? here.map((e) => {
          const was = prevE[e.id], now = Number((e.attrs || {})[size] || 0);
          const moved = was && was.place !== placeId ? ` <em>${t("arrived")} ${L(was.place)}</em>` : "";
          const v = was && was.place === placeId ? value(Number((was.attrs || {})[size] || 0), now) : `<span class="tv">${fmt(now)}</span>`;
          return force(e, moved, v);
        }).join("") + gone.map((e) => force(e, ` <em>${t("left")}</em>`, "")).join("")
      : `<div class="none">${t("no_forces")}</div>`;
    let aimed = "";
    if (c.turn) {
      const list = (c.actions || []).flatMap((dcl) => dcl.actions.filter((a) => a.place === placeId).map((a) => ({ actor: dcl.actor, a })));
      aimed = `<div class="tsec">${t("aimed_here")} ${c.turn}</div>` + (c.sealed
        ? `<div class="none">${t("still_sealed")}</div>`
        : list.length ? list.map((x) => `<div class="drow"><b style="color:${C.map.colour(run, x.actor)}">${L(x.actor)}</b> · ${L(x.a.type)}${x.a.intensity ? " ×" + x.a.intensity : ""}</div>`).join("")
        : `<div class="none">${t("nobody_aimed")}</div>`);
    }
    const when = c.prev ? `${t("after")} ${c.turn}` : c.turn ? `${t("at_start")} ${c.turn}` : t("initial");
    const holder = st.owner ? `${t("controlled_by")} ${L(st.owner)}` : t("open_water");
    return `<div class="th"><b>${L(placeId)}</b><span class="own" style="color:${st.owner ? C.map.colour(run, st.owner) : "#8a95a5"}">${holder}</span></div>
      <div class="tsub">${when}</div>${attrs}
      <div class="tsec">${t("forces_here")}</div>${forces}${aimed}
      <div class="tadj">${t("borders")}: ${(p.adjacency || []).map(L).join(", ")}${p.source ? ` · ${t("source")} <code>${esc(p.source)}</code>` : ""}</div>`;
  }

  // One card element per page, following the pointer. `refresh` re-reads what is
  // under a still pointer, because a map redrawn under it has a new context.
  let tip = null, mx = -1, my = -1, currentRun = null;
  function show(target, x, y) {
    const g = target && target.closest ? target.closest("[data-place]") : null;
    const svg = g && g.ownerSVGElement;
    const c = svg && C.map.context(svg.dataset.ctx);
    if (!c || !currentRun) { tip.style.display = "none"; tip.dataset.key = ""; return; }
    const key = svg.dataset.ctx + "/" + g.dataset.place;
    if (tip.dataset.key !== key) {
      tip.dataset.key = key;
      tip.innerHTML = html(currentRun, g.dataset.place, c);
      const st = (c.snapshot.places || {})[g.dataset.place] || {};
      tip.style.setProperty("--ac", st.owner ? C.map.colour(currentRun, st.owner) : "#8a95a5");
    }
    tip.style.display = "block";
    let left = x + 18, top = y + 14;
    if (left + tip.offsetWidth > innerWidth - 8) left = x - tip.offsetWidth - 18;
    if (top + tip.offsetHeight > innerHeight - 8) top = Math.max(8, innerHeight - tip.offsetHeight - 8);
    tip.style.left = left + "px"; tip.style.top = top + "px";
  }
  function attach(doc, run) {
    currentRun = run;
    if (tip) return;
    tip = doc.createElement("div"); tip.id = "tip"; doc.body.appendChild(tip);
    doc.addEventListener("mousemove", (e) => { mx = e.clientX; my = e.clientY; show(e.target, mx, my); });
  }
  function refresh() { if (tip && mx >= 0) show(document.elementFromPoint(mx, my), mx, my); }

  C.card = { html, attach, refresh, fmt };
})();
```

- [ ] **Step 5: Create `ui/css/app.css`**

Copy the whole `<style>` block of the mockup (`casus-v2.html`, from `:root{` to the closing `</style>`), minus the `.mockflag` rule, into `ui/css/app.css`. Then make three changes so it matches the scripts above:

1. Replace the font stacks in `:root` with system stacks, because the bundle must not load web fonts:
   ```css
   --sans: ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif;
   --mono: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
   --serif: Georgia, "Times New Roman", serif;
   ```
2. Add the rules the new markup uses:
   ```css
   .land{fill:#131b27;stroke:#26303f}
   .mk{stroke:#070b12}
   .target{fill:none;animation:ping 1.6s ease-out infinite;transform-box:fill-box;transform-origin:center}
   .nomap{display:flex;align-items:center;justify-content:center;height:100%;color:var(--faint);font-family:var(--mono);font-size:12px}
   #appshell{height:100vh;display:flex;flex-direction:column}
   .banner{position:absolute;left:50%;top:8px;transform:translateX(-50%);z-index:8;background:rgba(40,28,6,.95);border:1px solid #5c4a1f;border-radius:8px;padding:8px 14px;font-size:13px}
   #tip em{color:var(--accent);font-style:normal}
   ```
3. Delete the `.land.cu` and `.land.us` rules: country colouring by owner is not generic.
4. Keep the mockup's `#app{height:100vh;display:flex;flex-direction:column}` rule: it sizes the bundle's root (`<div id="app">` in `ui/bundle.html`), which `.visor{height:100%}` fills. The app's root is `#appshell`, sized by the rule added above; without it `#view` has no bounded height.

- [ ] **Step 6: Run to verify the card tests pass**

Run: `uv run pytest tests/test_ui_scripts.py -q`
Expected: PASS (7 tests).

- [ ] **Step 7: Commit**

```bash
git add ui/js/map.js ui/js/card.js ui/css/app.css tests/js/harness.js tests/test_ui_scripts.py
git commit -m "feat(ui): the theatre map and the place card"
```

---

### Task 6: The four-beat viewer (`viewer.js`)

**Files:**
- Create: `ui/js/viewer.js`
- Test: covered by the browser suite in Task 9; this task adds a `node --check` of every script.

**Interfaces:**
- Consumes: `Casus.records.*`, `Casus.map.*`, `Casus.card.*`, `Casus.i18n.t`.
- Produces: `Casus.viewer.mount(root, run, {mode}) -> {destroy(), state()}` where `state()` returns `{turn, beat, auto, frozen, done}` for tests. Beats are indexed 0 thinking, 1 declaring, 2 resolving, 3 dispatch. Live mode (`mode: "live"`) auto-advances; recorded mode waits for the arrow key.
- Hook for slice 4: `Casus.viewer.rationaleFor(run, turn, actorId, declared)` returns the text a pane shows. In this slice it returns `declared.rationale`; slice 4 makes it prefer `run.deltas[turn][actor]` while the declaration is not in.

- [ ] **Step 1: Write the failing syntax test**

Append to `tests/test_ui_scripts.py`:

```python
@pytest.mark.parametrize("name", sorted(p.name for p in (ROOT / "ui" / "js").glob("*.js")))
def test_every_ui_script_parses(name):
    """The scripts are classic so the bundle can concatenate them. node --check
    exits 0 on a .js file in ES module syntax even with a syntax error, so this
    test relies on ui/ staying classic."""
    done = subprocess.run(
        [NODE, "--check", str(ROOT / "ui" / "js" / name)], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr[:400]


def test_viewer_js_exists():
    assert (ROOT / "ui" / "js" / "viewer.js").is_file()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ui_scripts.py -q -k "viewer_js_exists"`
Expected: FAIL.

- [ ] **Step 3: Implement `ui/js/viewer.js`**

The structure and timings are the mockup's `visor()` function, rewritten over the `RunModel`. Write it as below.

```js
// The game viewer: one turn in four beats. Thinking and declaring happen in the
// war room (one pane per actor); resolving and the dispatch happen in the
// command post (the map fills the screen). Live, beats advance on a clock;
// recorded, they wait for the arrow key. `auto` and `frozen` are separate.
(function () {
  const C = (window.Casus = window.Casus || {});
  const t = (k) => C.i18n.t(k);
  const BEATS = ["thinking", "declaring", "resolving", "dispatch"];
  const HOLD = [1400, 2600, 0, 5200];     // ms a finished beat lingers when auto
  const PHASES = ["legality", "upkeep", "movement", "contest", "consequences"];

  function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); }
  function pad2(n) { return String(n).padStart(2, "0"); }
  function rationaleFor(run, turn, actorId, declared) { return declared ? declared.rationale : ""; }

  function mount(root, run, opts) {
    const live = opts.mode === "live";
    const V = { ti: 0, beat: 0, clock: 0, last: 0, hold: 0, auto: live, frozen: false, done: false, raf: 0, panes: [], cmd: null };
    const esc = C.map.esc, L = (k) => esc(C.records.label(run, k));
    const actors = C.records.actorIds(run);
    const lang = (run.header && run.header.language) || "en";
    C.i18n.use(lang);
    C.card.attach(document, run);

    root.innerHTML = `
      <div class="visor">
        <div class="vhead">
          <div><div class="scn">${esc(run.header ? run.header.name : "")} · seed ${run.header ? run.header.seed : ""}</div><div class="day" id="vday"></div></div>
          <div class="beats" id="vbeats">${BEATS.map((b) => `<div class="beat">${t(b)}</div>`).join("")}</div>
          <div class="sp"></div><div class="ready" id="vready"></div>
          <div>${live ? `<span class="livetag"><span class="livedot"></span>${t("live")}</span>` : `<span class="rectag">● ${t("recorded")}</span>`}</div>
        </div>
        <div class="stage" id="stage"></div>
        <div class="controls chrome">
          <button class="iconbtn" id="bprev">◀</button><button class="iconbtn" id="bplay"></button><button class="iconbtn" id="bnext">▶</button>
          <div class="dots" id="vdots"></div><div class="sp"></div><div class="keys">${t("keys")}</div>
        </div>
      </div>`;
    const $ = (s) => root.querySelector(s);

    const turns = () => run.playable();
    const T = () => turns()[V.ti];
    function header() {
      const cur = T();
      $("#vday").innerHTML = cur ? `${t("day")} ${pad2(cur.turn)}<small>/ ${run.header ? run.header.turns : ""}</small>` : "";
      [...$("#vbeats").children].forEach((el, i) => { el.className = "beat" + (i === V.beat ? " on" : i < V.beat ? " past" : ""); });
      $("#vdots").innerHTML = turns().map((x, i) => `<div class="dot${i === V.ti ? " cur" : i < V.ti ? " done" : ""}" data-i="${i}"></div>`).join("");
      $("#bplay").textContent = V.auto ? t("auto_on") : t("auto_off");
      $("#stage").classList.toggle("frozen", V.frozen);
    }
    function enter(beat) {
      V.beat = beat; V.clock = 0; V.hold = 0;
      if (!T()) return;
      if (beat === 0) warRoom(); else if (beat === 1) reveal(); else if (beat === 2) commandPost(); else dispatch();
      header(); C.card.refresh();
    }

    // ---- beats 0-1: the war room ----
    function mapCtx(extra) { return Object.assign({ turn: T().turn }, extra); }
    function warRoom() {
      const cur = T(), r = rng(cur.turn * 7919 + 17), declared = C.records.declarations(cur);
      V.panes = actors.map((id) => {
        const d = declared.find((x) => x.actor === id) || null;
        const prompt = cur.prompts.find((p) => p.actor === id);
        return { id, d, model: prompt ? prompt.model : "", start: 500 + r() * 2600, cps: 38 + r() * 55 };
      });
      const hasLadder = !!(run.scenario.display || {}).ladder;
      $("#stage").innerHTML = `
        <div class="war">
          <div class="panes" style="grid-template-columns:repeat(${Math.max(1, V.panes.length)},1fr)">${V.panes.map((p) => `
            <div class="pane" id="pane-${esc(p.id)}" style="--ac:${C.map.colour(run, p.id)}" onclick="this.classList.toggle('open')">
              <div class="who"><b>${L(p.id)}</b><span class="model">${esc(p.model)}</span></div>
              <div class="status"></div>
              <div class="chips"><div class="sealed">${t("sealed")}</div></div>
              <div class="text"></div>
              <div class="assess">${t("expects")} <em>${esc(p.d ? p.d.assessment : "")}</em></div>
            </div>`).join("")}</div>
          <div class="board" style="grid-template-columns:${hasLadder ? "1.25fr 1fr 1.1fr" : "1.4fr 1fr"}">
            <div class="bpanel"><div class="lbl">${t("theatre")}</div><svg id="boardmap"></svg></div>
            ${hasLadder ? `<div class="bpanel"><div class="lbl">${t("ladder")}</div>${ladderHTML(cur.before)}</div>` : ""}
            <div class="bpanel"><div class="lbl">${t("standing")}</div>${standingHTML(cur.before)}</div>
          </div>
          ${cur.complete ? "" : `<div class="banner">${t("incomplete")}</div>`}
        </div>`;
      C.map.draw($("#boardmap"), run, cur.before, { font: 2.2, ctx: mapCtx({ sealed: true }) });
    }
    function ladderHTML(snap) {
      const lad = run.scenario.display.ladder, rungs = lad[lang] || lad.en || [];
      return `<div class="ladder">${actors.map((id) => {
        const rung = Math.round(Number(((snap.actors[id] || {}).resources || {})[lad.resource] || 0));
        return `<div class="lrow" style="--ac:${C.map.colour(run, id)}"><div>${L(id)}</div><div class="cells" style="grid-template-columns:repeat(${rungs.length},1fr)">${rungs.map((name, i) => `<div class="cell${i <= rung ? " on" : ""}${i === rung ? " top" : ""}" title="${esc(name)}"></div>`).join("")}</div></div>`;
      }).join("")}</div>`;
    }
    function scaleOf(k) {
      const d = run.scenario.display || {};
      const max = ((run.scenario.resources || {})[k] || {}).max;
      if ((d.scale || {})[k]) return Number(d.scale[k]);
      if (typeof max === "number") return max;
      const first = turns()[0];
      return Math.max(1, ...actors.map((id) => Number((((first.before.actors[id] || {}).resources) || {})[k] || 0))) * 1.2;
    }
    function standingHTML(snap) {
      const keys = (run.scenario.display || {}).standing || [];
      return `<div class="stand"><div class="shead" style="grid-template-columns:62px repeat(${keys.length},1fr)"><div></div>${keys.map((k) => `<div>${L(k)}</div>`).join("")}</div>
        ${actors.map((id) => `<div class="srow" style="--ac:${C.map.colour(run, id)};grid-template-columns:62px repeat(${keys.length},1fr)"><div>${L(id)}</div>${keys.map((k) => {
          const v = Number((((snap.actors[id] || {}).resources) || {})[k] || 0);
          return `<div class="bar" title="${L(k)}: ${C.card.fmt(v)}"><i style="width:${Math.min(100, (v / scaleOf(k)) * 100)}%"></i></div>`;
        }).join("")}</div>`).join("")}</div>`;
    }
    function paneFrame() {
      let done = 0;
      for (const p of V.panes) {
        const el = document.getElementById("pane-" + p.id); if (!el) continue;
        const txt = rationaleFor(run, T().turn, p.id, p.d) || "";
        const n = V.clock < p.start ? 0 : Math.min(txt.length, Math.floor(((V.clock - p.start) / 1000) * p.cps));
        const st = el.querySelector(".status");
        const finished = p.d && n >= txt.length;
        if (!p.d && !live) { st.textContent = "—"; done++; continue; }
        if (V.clock < p.start || (!txt.length && !p.d)) { st.textContent = t("thinking") + ".".repeat(1 + (Math.floor(V.clock / 400) % 3)); st.className = "status"; el.classList.remove("writing"); }
        else if (!finished) { st.textContent = t("writing"); st.className = "status"; el.classList.add("writing"); }
        else { st.textContent = "✓ " + t("ready"); st.className = "status done"; el.classList.remove("writing"); done++; }
        const tx = el.querySelector(".text");
        tx.innerHTML = esc(txt.slice(0, n)) + (n > 0 && n < txt.length ? '<span class="cur"></span>' : "");
        tx.scrollTop = tx.scrollHeight;
      }
      $("#vready").innerHTML = `<b>${pad2(done)}</b> / ${pad2(V.panes.length)} ${t("ready_count")}`;
      return done === V.panes.length;
    }
    function reveal() {
      for (const p of V.panes) {
        const el = document.getElementById("pane-" + p.id); if (!el || !p.d) continue;
        el.classList.add("revealed");
        el.querySelector(".chips").innerHTML = p.d.actions.map((a, i) => `<div class="chip" style="animation-delay:${actors.indexOf(p.id) * 0.12 + i * 0.08}s">${L(a.type)}${a.place ? `<span class="tgt">▸ ${L(a.place)}</span>` : a.target ? `<span class="tgt">▸ ${L(a.target)}</span>` : ""}<span class="int">${a.intensity ? "×" + a.intensity : ""}</span></div>`).join("");
      }
      const declared = C.records.declarations(T());
      const targets = declared.flatMap((d) => d.actions.filter((a) => a.place).map((a) => ({ actor: d.actor, place: a.place })));
      const svg = $("#boardmap");
      if (svg) C.map.draw(svg, run, T().before, { targets, font: 2.2, ctx: mapCtx({ actions: declared }) });
      $("#vready").innerHTML = `<b>${pad2(declared.length)}</b> / ${pad2(V.panes.length)} ${t("declared_count")}`;
    }

    // ---- beats 2-3: the command post ----
    function deltas(cur) {
      const out = [], keys = (run.scenario.display || {}).standing || [];
      const worse = new Set((run.scenario.display || {}).worse_when_higher || []);
      if (!cur.after) return out;
      for (const id of actors) for (const k of keys) {
        const a = Number(((cur.before.actors[id] || {}).resources || {})[k] || 0);
        const b = Number(((cur.after.actors[id] || {}).resources || {})[k] || 0);
        if (Math.abs(b - a) >= 0.5) out.push({ ac: C.map.colour(run, id), what: `${L(k)} · ${L(id)}`, a, b, w: Math.abs(b - a) / Math.max(1, scaleOf(k) / 10) });
      }
      for (const [pid, p] of Object.entries(cur.after.places || {})) for (const k of (run.scenario.display || {}).card || []) {
        const a = Number(((cur.before.places[pid] || {}).attrs || {})[k] || 0), b = Number((p.attrs || {})[k] || 0);
        if (Math.abs(b - a) >= 0.5) out.push({ ac: "#ff8a9b", what: `${L(k)} · ${L(pid)}`, a, b, worse: worse.has(k), w: Math.abs(b - a) / 8 });
      }
      return out.sort((x, y) => y.w - x.w).slice(0, 6);
    }
    function aspect() { const s = $("#stage"); return s ? s.clientWidth / Math.max(300, s.clientHeight) : 2; }
    function commandPost() {
      const cur = T(), declared = C.records.declarations(cur);
      const targets = declared.flatMap((d) => d.actions.filter((a) => a.place).map((a) => ({ actor: d.actor, place: a.place })));
      V.cmd = { deltas: deltas(cur), shown: 0, events: cur.events, swapped: false };
      $("#stage").innerHTML = `
        <div class="cmd">
          <div class="bigmap"><svg id="bigmap"></svg></div><div class="vign"></div>
          <div class="phases" id="phases">${PHASES.map((p) => `<div class="phase">${esc(p)}</div>`).join("")}<div class="ledger" id="ledger"></div></div>
          <div class="deltas" id="deltas"></div>
          <div class="hud" style="grid-template-columns:repeat(${Math.max(1, actors.length)},1fr)">${actors.map((id) => { const d = declared.find((x) => x.actor === id); return `<div class="hudc" style="--ac:${C.map.colour(run, id)}"><b>${L(id)}</b>${d ? d.actions.map((a) => `<div class="a">${L(a.type)}${a.place ? " ▸ " + L(a.place) : ""}</div>`).join("") : ""}</div>`; }).join("")}</div>
          ${cur.complete ? "" : `<div class="banner">${t("incomplete")}</div>`}
          ${run.error && run.error.turn === cur.turn ? `<div class="banner">${t("failed")} ${esc(run.error.error)}</div>` : ""}
        </div>`;
      C.map.draw($("#bigmap"), run, cur.before, { targets, aspect: aspect(), slice: true, font: 1.25, edges: true, rscale: 0.5, ctx: mapCtx({ actions: declared }) });
      $("#vready").innerHTML = `<b>${cur.mutations}</b> ${t("mutations")}`;
    }
    function commandFrame() {
      const cur = T(), k = Math.floor(V.clock / 520);
      [...$("#phases").querySelectorAll(".phase")].forEach((el, i) => { el.className = "phase" + (i === k ? " on" : i < k ? " past" : ""); });
      if (k >= PHASES.length && !V.cmd.swapped) {
        V.cmd.swapped = true;
        $("#ledger").textContent = `${cur.mutations} ${t("ledger")}`;
        if (cur.after) {
          C.map.draw($("#bigmap"), run, cur.after, { aspect: aspect(), slice: true, font: 1.25, edges: true, rscale: 0.5,
            ctx: mapCtx({ prev: cur.before, actions: C.records.declarations(cur) }) });
          setTimeout(C.card.refresh);
        }
      }
      const total = V.cmd.events.length + V.cmd.deltas.length;
      const want = k < PHASES.length ? 0 : Math.min(total, Math.floor((V.clock - 2600) / 380) + 1);
      const box = $("#deltas");
      while (V.cmd.shown < want) {
        const i = V.cmd.shown++;
        if (i < V.cmd.events.length) {
          const e = V.cmd.events[i];
          box.insertAdjacentHTML("beforeend", `<div class="evt"><b>${L(e.id)}</b>${esc((e.detail || {}).reason || "")}</div>`);
        } else {
          const d = V.cmd.deltas[i - V.cmd.events.length];
          box.insertAdjacentHTML("beforeend", `<div class="delta" style="--ac:${d.ac}"><span class="what">${d.what}</span><span class="num ${(d.b < d.a) !== !!d.worse ? "down" : "up"}" data-a="${d.a}" data-b="${d.b}" data-t="${V.clock}">${C.card.fmt(d.a)}</span></div>`);
        }
      }
      box.querySelectorAll(".num").forEach((el) => {
        const a = +el.dataset.a, b = +el.dataset.b, f = Math.min(1, (V.clock - +el.dataset.t) / 1200);
        el.textContent = f < 1 ? C.card.fmt(a + (b - a) * (1 - Math.pow(1 - f, 3))) : `${C.card.fmt(a)} → ${C.card.fmt(b)}`;
      });
      return k >= PHASES.length && V.cmd.shown >= total && V.clock > 2600 + want * 380 + 1400;
    }
    function dispatch() {
      const cur = T(), declared = C.records.declarations(cur);
      const lines = declared.map((d) => `<li><b>${L(d.actor)}</b>: ${d.actions.map((a) => L(a.type) + (a.place ? " · " + L(a.place) : "")).join(", ")}</li>`).join("");
      $("#stage").insertAdjacentHTML("beforeend", `
        <div class="dispatch" id="dispatch">
          <div class="kick"><span>${t("dispatch_of")} ${cur.turn}</span><span>${esc(run.header ? run.header.name : "")}</span></div>
          <h2>${esc(cur.narrative || t("no_dispatch"))}</h2><ul>${lines}</ul>
        </div>`);
    }
    function finale() {
      $("#stage").insertAdjacentHTML("beforeend", `<div class="finale"><div class="box"><div class="rectag">${t("end")}</div><h2>${esc(run.header ? run.header.name : "")}</h2></div></div>`);
    }

    // ---- the clock and the keys ----
    function next() {
      if (V.done || !T()) return;
      if (V.beat === 0) { if (!paneFrame() && !live) { V.clock = 1e9; paneFrame(); return; } enter(1); }
      else if (V.beat < 3) enter(V.beat + 1);
      else if (V.ti < turns().length - 1) { V.ti++; enter(0); }
      else if (!live || run.ended) { V.done = true; finale(); }
    }
    function prev() {
      if (V.done) { V.done = false; const f = root.querySelector(".finale"); if (f) f.remove(); return; }
      if (V.beat === 0) { if (V.ti > 0) { V.ti--; enter(0); V.clock = 1e9; } }
      else if (V.beat === 1) { enter(0); V.clock = 1e9; }
      else if (V.beat === 2) { enter(0); V.clock = 1e9; paneFrame(); enter(1); }
      else { const d = $("#dispatch"); if (d) d.remove(); V.beat = 2; header(); }
    }
    function frame(ts) {
      const dt = V.last ? ts - V.last : 0; V.last = ts;
      if (!V.frozen && !V.done) V.clock += dt;
      if (!V.done && T()) {
        let finished;
        if (V.beat === 0) finished = paneFrame();
        else if (V.beat === 1) finished = V.clock > 900;
        else if (V.beat === 2) finished = commandFrame();
        else finished = true;
        if (finished && V.auto && !V.frozen) { V.hold += dt; if (V.hold > HOLD[V.beat]) next(); }
        else if (!finished) V.hold = 0;
      }
      V.raf = requestAnimationFrame(frame);
    }
    function key(e) {
      if (/INPUT|TEXTAREA/.test(e.target.tagName)) return;
      if (e.key === "ArrowRight") { e.preventDefault(); V.hold = 0; next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); prev(); }
      else if (e.key === " ") { e.preventDefault(); V.frozen = !V.frozen; header(); }
      else if (e.key === "p" || e.key === "P") document.body.classList.toggle("present");
      else if (e.key === "Escape") document.body.classList.remove("present");
    }
    document.addEventListener("keydown", key);
    $("#bnext").onclick = next; $("#bprev").onclick = prev;
    $("#bplay").onclick = () => { V.auto = !V.auto; header(); };
    $("#vdots").onclick = (e) => { const i = e.target.dataset.i; if (i !== undefined) { V.done = false; V.ti = +i; enter(0); } };

    // A live run may start with no playable turn; enter the first when it appears.
    const onChange = () => { if (V.beat === 0 && !V.panes.length && T()) enter(0); else header(); };
    run.onChange(onChange);
    if (T()) enter(0); else header();
    V.raf = requestAnimationFrame(frame);
    return {
      destroy() { cancelAnimationFrame(V.raf); document.removeEventListener("keydown", key); },
      state() { return { turn: T() ? T().turn : null, beat: V.beat, auto: V.auto, frozen: V.frozen, done: V.done }; },
    };
  }

  C.viewer = { mount, rationaleFor, BEATS };
})();
```

The phase names come from the engine's five fixed phases. They are identifiers, so the viewer labels them through `Casus.records.label`, which lets a scenario translate them in `display.labels`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ui_scripts.py -q`
Expected: PASS, including one `test_every_ui_script_parses[...]` case per script.

- [ ] **Step 5: Commit**

```bash
git add ui/js/viewer.js tests/test_ui_scripts.py
git commit -m "feat(ui): the four-beat game viewer"
```

---

### Task 7: The offline bundle on the new viewer

**Files:**
- Create: `ui/bundle.html`
- Modify: `src/casus/bundle.py`
- Delete: `ui/replay.html`
- Test: `tests/test_bundle.py`

**Interfaces:**
- Produces: `bundle.SCRIPTS` (the ordered tuple of script names the bundle inlines), `bundle.bundle(transcript, out, template=None, worldmap=None) -> Path` (same signature as today).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bundle.py`:

```python
def test_the_bundle_inlines_every_viewer_script_in_order(transcript, tmp_path):
    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    positions = [html.index(f"/* ui/js/{name} */") for name in bundle.SCRIPTS]
    assert positions == sorted(positions)
    assert bundle.SCRIPTS == ("i18n.js", "records.js", "map.js", "card.js", "viewer.js")


def test_the_bundle_boots_the_viewer_in_recorded_mode(transcript, tmp_path):
    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    assert 'Casus.viewer.mount(' in html and '"recorded"' in html


def test_no_script_or_style_in_the_bundle_names_a_web_font(transcript, tmp_path):
    html = bundle.bundle(transcript, tmp_path / "demo.html").read_text()
    assert "fonts.googleapis" not in html and "@import" not in html
```

Update `test_the_bundled_script_is_syntactically_valid` to take the largest `<script>` block, since the bundle now carries a JSON data block and the code block:

```python
    code = max(re.findall(r"<script>(.*?)</script>", html, re.DOTALL), key=len)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_bundle.py -q`
Expected: FAIL on the three new tests.

- [ ] **Step 3: Create `ui/bundle.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>casus</title>
<style>__CASUS_STYLE__</style>
</head>
<body>
<div id="app"></div>
<script id="casus-data" type="application/json">__CASUS_DATA__</script>
<script id="casus-worldmap" type="application/json">__CASUS_WORLDMAP__</script>
<script>
window.CASUS_WORLDMAP = JSON.parse(document.getElementById("casus-worldmap").textContent);
__CASUS_SCRIPTS__
(function () {
  var run = new Casus.records.RunModel();
  JSON.parse(document.getElementById("casus-data").textContent).forEach(function (r) { run.push(r); });
  Casus.viewer.mount(document.getElementById("app"), run, { mode: "recorded" });
})();
</script>
</body>
</html>
```

- [ ] **Step 4: Implement in `src/casus/bundle.py`**

```python
UI = pathlib.Path(__file__).parent.parent.parent / "ui"
TEMPLATE = UI / "bundle.html"
WORLDMAP = UI / "worldmap.json"
STYLE = UI / "css" / "app.css"

#: The viewer's scripts, in load order. The app loads the same files by URL.
SCRIPTS = ("i18n.js", "records.js", "map.js", "card.js", "viewer.js")

STYLE_TOKEN = "__CASUS_STYLE__"
SCRIPTS_TOKEN = "__CASUS_SCRIPTS__"


def _scripts() -> str:
    return "\n".join(
        f"/* ui/js/{name} */\n" + (UI / "js" / name).read_text() for name in SCRIPTS
    )
```

In `bundle()`, after `html = (template or TEMPLATE).read_text()`, fill the two new tokens before the data and the map. Escape the scripts the same way as the data, since a literal `</script` inside them would end the block:

```python
    html = html.replace(STYLE_TOKEN, STYLE.read_text())
    html = html.replace(SCRIPTS_TOKEN, _escape(_scripts()))
```

Order matters: replace `STYLE_TOKEN` and `SCRIPTS_TOKEN` before `DATA_TOKEN`, so a transcript that happens to contain the text `__CASUS_SCRIPTS__` cannot inject into the page.

Delete `ui/replay.html`: `git rm ui/replay.html`.

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_bundle.py -q`
Expected: PASS, all tests, old and new.

- [ ] **Step 6: Commit**

```bash
git add ui/bundle.html src/casus/bundle.py tests/test_bundle.py
git commit -m "feat(bundle): the offline bundle plays the new viewer"
```

---

### Task 8: The server and the shell (`casus serve`)

**Files:**
- Create: `src/casus/server/__init__.py`, `src/casus/server/app.py`
- Create: `ui/app.html`, `ui/js/shell.js`
- Modify: `src/casus/cli.py`, `pyproject.toml`
- Test: `tests/test_server.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `studies.list_runs`, `bundle.viewer_records`, `engine.read_records`, `Scenario.load`.
- Produces: `create_app(*, scenarios_dir, runs_dir, settings=None) -> FastAPI` (master plan), `GET /`, `GET /ui/...`, `GET /api/scenarios`, `GET /api/runs`, `GET /api/runs/{id}`. `Casus.shell.start()`.

- [ ] **Step 1: Add the dependencies**

In `pyproject.toml`, set `requires-python = ">=3.13"` (lovelaice, which slices 6 and 7 add as a normal dependency, requires it, and casus is one package with no optional extras), add to `dependencies`: `"fastapi>=0.115"`, `"uvicorn>=0.30"`; add to the `dev` group: `"playwright>=1.47"`. Run `uv lock && uv sync`; uv fetches a 3.13 interpreter if none is installed.

- [ ] **Step 2: Write the failing server tests**

Create `tests/test_server.py`:

```python
import pathlib

import pytest
from fastapi.testclient import TestClient

from casus import engine
from casus.scenario import Scenario
from casus.server.app import create_app
from helpers import FakeEngine

ROOT = pathlib.Path(__file__).parent.parent
SCENARIOS = ROOT / "scenarios"


@pytest.fixture
def runs(tmp_path) -> pathlib.Path:
    scenario = Scenario.load(SCENARIOS / "smoke")
    engines = {a: FakeEngine() for a in scenario.actors}
    engine.run(scenario, seed=5, out=tmp_path / "smoke-5.jsonl", engines=engines, turns=2)
    return tmp_path


@pytest.fixture
def client(runs) -> TestClient:
    return TestClient(create_app(scenarios_dir=SCENARIOS, runs_dir=runs))


def test_the_home_page_loads_the_scripts_in_order(client):
    html = client.get("/").text
    order = [html.index(f'/ui/js/{n}') for n in ("i18n.js", "records.js", "map.js", "card.js", "viewer.js", "shell.js")]
    assert order == sorted(order)
    assert "casus-worldmap" in html


def test_scripts_are_served(client):
    assert client.get("/ui/js/viewer.js").status_code == 200


def test_scenarios_list_the_shipped_ones_with_their_counts(client):
    by_name = {s["name"]: s for s in client.get("/api/scenarios").json()}
    smoke = by_name["smoke"]
    assert (smoke["actors"], smoke["places"], smoke["turns"]) == (2, 3, 3)
    assert smoke["valid"] is True and smoke["findings"] == []


def test_runs_are_listed(client):
    [run] = client.get("/api/runs").json()
    assert (run["id"], run["scenario"], run["status"]) == ("smoke-5", "smoke", "complete")


def test_a_run_is_served_as_viewer_records(client):
    records = client.get("/api/runs/smoke-5").json()
    kinds = {r["kind"] for r in records}
    assert "ledger" in kinds and "mutation" not in kinds


def test_an_unknown_run_is_a_404(client):
    assert client.get("/api/runs/nope").status_code == 404


@pytest.mark.parametrize("bad", ["..%2Fsmoke-5", "a/b", ".hidden", "x y"])
def test_a_run_id_cannot_leave_the_runs_directory(client, bad):
    assert client.get(f"/api/runs/{bad}").status_code == 404
```

Append to `tests/test_cli.py`:

```python
def test_serve_starts_uvicorn_on_loopback(monkeypatch):
    calls = {}

    def fake_run(app, host, port, log_level):
        calls.update(host=host, port=port)

    monkeypatch.setattr("uvicorn.run", fake_run)
    assert cli.main(["serve", "--no-open", "--port", "8765"]) == 0
    assert calls == {"host": "127.0.0.1", "port": 8765}
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_server.py tests/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'casus.server'`.

- [ ] **Step 4: Implement `src/casus/server/app.py`**

```python
"""The local app. It binds loopback only and serves one person at a laptop."""

from __future__ import annotations

import functools
import pathlib
import re

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import bundle, engine, studies
from ..scenario import Scenario, ScenarioError

UI = pathlib.Path(__file__).parent.parent.parent.parent / "ui"
APP_SCRIPTS = (*bundle.SCRIPTS, "shell.js")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def scenario_dirs(root: pathlib.Path) -> list[pathlib.Path]:
    """Shipped scenarios, then those behind the private link when it resolves."""
    shipped = sorted(p.parent for p in root.glob("*/scenario.yaml"))
    private = sorted(p.parent for p in root.glob("private/*/scenario.yaml"))
    return [*shipped, *private]


@functools.lru_cache(maxsize=64)
def _verdict(directory: str, stamp: float) -> tuple[bool, tuple[str, ...]]:
    """Full validation is slow (a dry turn, two processes), so it is cached per
    directory and modification time."""
    try:
        Scenario.load(directory)
        return True, ()
    except ScenarioError as exc:
        return False, tuple(str(exc).splitlines())


def _card(directory: pathlib.Path) -> dict:
    stamp = max(p.stat().st_mtime for p in directory.iterdir() if p.is_file())
    valid, findings = _verdict(str(directory), stamp)
    data = Scenario.load(directory, validate=False).data
    return {
        "name": data["name"], "dir": directory.name, "actors": len(data["actors"]),
        "places": len(data["places"]), "turns": data.get("turns"),
        "description": data.get("description", ""), "valid": valid, "findings": list(findings),
    }


def create_app(*, scenarios_dir: pathlib.Path, runs_dir: pathlib.Path, settings=None) -> FastAPI:
    app = FastAPI(title="casus", docs_url=None, redoc_url=None)
    app.mount("/ui", StaticFiles(directory=UI), name="ui")

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        html = (UI / "app.html").read_text()
        tags = "\n".join(f'<script src="/ui/js/{n}"></script>' for n in APP_SCRIPTS)
        return html.replace("__CASUS_SCRIPTS__", tags).replace(
            "__CASUS_WORLDMAP__", bundle._escape((UI / "worldmap.json").read_text())
        )

    @app.get("/api/scenarios")
    def scenarios() -> list[dict]:
        return [_card(d) for d in scenario_dirs(scenarios_dir)]

    @app.get("/api/runs")
    def runs() -> list[dict]:
        return [r.to_json() for r in studies.list_runs(runs_dir)]

    @app.get("/api/runs/{run_id}")
    def run(run_id: str) -> list[dict]:
        path = runs_dir / f"{run_id}.jsonl"
        if not RUN_ID.match(run_id) or path.resolve().parent != runs_dir.resolve() or not path.is_file():
            raise HTTPException(404, "no such run")
        return bundle.viewer_records(engine.read_records(path))

    return app
```

Create `src/casus/server/__init__.py` empty except a one-line docstring: `"""The local app server."""`.

- [ ] **Step 5: Create `ui/app.html` and `ui/js/shell.js`**

`ui/app.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>casus</title>
<link rel="stylesheet" href="/ui/css/app.css">
</head>
<body>
<div id="appshell">
  <div class="topbar chrome"><div class="brand" onclick="location.hash='#/'">cas<b>us</b></div><div class="crumbs" id="crumbs"></div><div class="sp"></div><div id="topactions"></div></div>
  <div id="view"></div>
</div>
<script id="casus-worldmap" type="application/json">__CASUS_WORLDMAP__</script>
<script>window.CASUS_WORLDMAP = JSON.parse(document.getElementById("casus-worldmap").textContent);</script>
__CASUS_SCRIPTS__
<script>Casus.shell.start();</script>
</body>
</html>
```

`ui/js/shell.js`:

```js
// The app shell: a home with two shelves, and hash routes that fill the screen.
// Later slices register more routes with Casus.shell.route(name, fn).
(function () {
  const C = (window.Casus = window.Casus || {});
  const routes = {};
  let current = null;
  const esc = (s) => C.map.esc(s);
  const view = () => document.getElementById("view");

  async function json(url) { const r = await fetch(url); if (!r.ok) throw new Error(url + " " + r.status); return r.json(); }

  function route(name, fn) { routes[name] = fn; }

  async function home() {
    const [scenarios, runs] = await Promise.all([json("/api/scenarios"), json("/api/runs")]);
    const byScenario = {};
    for (const r of runs) (byScenario[r.scenario] = byScenario[r.scenario] || []).push(r);
    view().innerHTML = `
      <div class="home">
        <div class="hero"><h1>cas<i>us</i></h1></div>
        <section class="shelf"><h2>${C.i18n.t("scenarios")}</h2><div class="row">${scenarios.map((s) => `
          <div class="card" data-scenario="${esc(s.dir)}"><h3>${esc(s.name)}</h3>
            <div class="meta">${s.actors} · ${s.places} · ${s.turns}</div><p>${esc(s.description || "")}</p>
            <div class="acts"><span class="badge ${s.valid ? "ok" : "bad"}">${s.valid ? "✓" : "✗ " + esc(s.findings[0] || "")}</span></div>
            <div class="acts" data-actions="scenario"></div></div>`).join("")}</div></section>
        <section class="shelf"><h2>${C.i18n.t("studies")}</h2><div class="row">${Object.entries(byScenario).map(([name, rs]) => `
          <div class="card" data-study="${esc(name)}"><h3>${esc(name)} <span class="meta">· ${rs.length}</span></h3>
            <div class="runlist">${rs.map((r) => `<div class="runrow"><div class="meta">${esc(r.id)}<br>${r.turns_done}/${r.turns_planned} · ${esc(r.status)}</div>
              <button class="btn small" onclick="location.hash='#/view/${encodeURIComponent(r.id)}'">${C.i18n.t("view")} ▸</button></div>`).join("")}</div>
            <div class="acts" data-actions="study"></div></div>`).join("")}</div></section>
      </div>`;
    for (const fn of hooks.home) fn(view());
  }

  async function viewRun(id) {
    const records = await json("/api/runs/" + encodeURIComponent(id));
    const run = new C.records.RunModel();
    for (const r of records) run.push(r);
    view().innerHTML = "";
    const handle = C.viewer.mount(view(), run, { mode: "recorded" });
    return () => handle.destroy();
  }

  const hooks = { home: [] };
  function onHome(fn) { hooks.home.push(fn); }

  async function dispatch() {
    if (current) { current(); current = null; }
    document.body.classList.remove("present");
    const [, name, ...parts] = (location.hash || "#/").split("/");
    const args = parts.map(decodeURIComponent);
    document.getElementById("crumbs").textContent = name ? `› ${name} · ${args.join(" · ")}` : "";
    // A route gets every path segment after its name: #/study/<scenario>/<version> has two.
    if (name === "view") current = await viewRun(args[0]);
    else if (routes[name]) current = await routes[name](view(), ...args);
    else await home();
  }

  function start() {
    window.addEventListener("hashchange", dispatch);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !document.body.classList.contains("present")) location.hash = "#/"; });
    dispatch();
  }

  C.shell = { start, route, onHome, json };
})();
```

- [ ] **Step 6: Add `casus serve` to `src/casus/cli.py`**

Next to the other subparsers in `main`:

```python
    serve_cmd = sub.add_parser("serve", help="open the app in a browser, on this machine only")
    serve_cmd.add_argument("--scenarios", default="scenarios")
    serve_cmd.add_argument("--runs", default="runs")
    serve_cmd.add_argument("--port", type=int, default=8321)
    serve_cmd.add_argument("--no-open", action="store_true")
```

and the dispatch branch `if args.command == "serve": return _serve(args)`, placed with the other `if args.command == ...` branches and before the final `return _verify(...)`, which is the fall-through for `verify` and `replay`. Then add:

```python
def _serve(args) -> int:
    import threading
    import webbrowser

    import uvicorn

    from .server.app import create_app

    app = create_app(
        scenarios_dir=pathlib.Path(args.scenarios), runs_dir=pathlib.Path(args.runs)
    )
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_open:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"casus: {url}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0
```

- [ ] **Step 7: Run to verify it passes**

Run: `uv run pytest tests/test_server.py tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/casus/server ui/app.html ui/js/shell.js src/casus/cli.py \
  tests/test_server.py tests/test_cli.py
git commit -m "feat(server): casus serve, the shell, and the read-only endpoints"
```

---

### Task 9: The browser suite and its CI job

**Files:**
- Create: `tests/browser/conftest.py`, `tests/browser/browser_support.py`, `tests/browser/test_viewer.py`, `tests/browser/test_app.py` (no `__init__.py`: the suite imports like the rest of `tests/`, and a module named `conftest` would collide with `tests/conftest.py`, so shared helpers live in `browser_support.py`)
- Modify: `.github/workflows/tests.yml`, `Makefile`

**Interfaces:**
- Produces fixtures later slices reuse: `page` (a Playwright page that fails the test on any console error or page error), `bundle_url(records) -> str` (writes a bundle from records and returns a `file://` URL), `app_url` (a running `casus serve` on a free port over a temporary runs directory).
- Produces helpers in `tests/browser/browser_support.py`: `run_records(tmp_path, scenario_dir="reference", turns=2, reply=None) -> list[dict]`, `beat(page) -> str`, `step_to(page, turn, beat_name)`, `serve(runs_dir) -> (url, stop)`.

- [ ] **Step 1: Write the fixtures**

`tests/browser/browser_support.py`:

```python
"""Helpers the browser tests share. Not a conftest, so it can be imported."""

from __future__ import annotations

import concurrent.futures
import json
import pathlib
import socket
import threading
import time

from casus import engine
from casus.scenario import Scenario
from helpers import FakeEngine

ROOT = pathlib.Path(__file__).parent.parent.parent


def run_records(tmp_path: pathlib.Path, scenario_dir="reference", turns=2, reply=None) -> list[dict]:
    """Record a run with fake engines. On a worker thread, because Playwright's sync
    API keeps an event loop running on the test thread and `engine.run` calls
    `asyncio.run`, which refuses to start inside a running loop."""
    scenario = Scenario.load(ROOT / "scenarios" / scenario_dir)
    out = tmp_path / f"{scenario.name}.jsonl"
    engines = {a: FakeEngine(reply) for a in scenario.actors}
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        pool.submit(engine.run, scenario, seed=1, out=out, engines=engines, turns=turns).result()
    return engine.read_records(out)


def write_run(runs_dir: pathlib.Path, name: str, records: list[dict]) -> pathlib.Path:
    path = runs_dir / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(runs_dir: pathlib.Path, **app_kwargs):
    """Start the real app on a free loopback port. Returns (url, stop)."""
    import uvicorn

    from casus.server.app import create_app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(
        create_app(scenarios_dir=ROOT / "scenarios", runs_dir=runs_dir, **app_kwargs),
        host="127.0.0.1", port=port, log_level="warning",
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    def stop():
        server.should_exit = True
        thread.join(timeout=5)

    return f"http://127.0.0.1:{port}/", stop


def beat(page) -> str:
    return page.locator(".beat.on").inner_text().strip().lower()


def step_to(page, turn: int, beat_name: str) -> None:
    for _ in range(200):
        day = page.locator("#vday").inner_text()
        if day.split()[1].startswith(f"{turn:02d}") and beat(page) == beat_name:
            return
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(30)
    raise AssertionError(f"never reached day {turn}, {beat_name}")
```

`tests/browser/conftest.py`:

```python
"""Real Chromium over the real viewer. Skips when Playwright or its browser is
missing, so a laptop without them still runs `make test`; CI installs both."""

from __future__ import annotations

import json

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

from browser_support import run_records, serve, write_run  # noqa: E402

from casus import bundle  # noqa: E402


@pytest.fixture(scope="session")
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # the executable is not installed
            pytest.skip(f"chromium is not installed: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1600, "height": 900})
    pg = ctx.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
    yield pg
    ctx.close()
    assert not errors, errors


@pytest.fixture
def bundle_url(tmp_path):
    def make(records: list[dict]) -> str:
        src = tmp_path / "in.jsonl"
        src.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return bundle.bundle(src, tmp_path / "out.html").as_uri()

    return make


@pytest.fixture
def app_url(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    write_run(runs, "reference-1", run_records(tmp_path))
    url, stop = serve(runs)
    yield url
    stop()
```

- [ ] **Step 2: Write the viewer tests**

`tests/browser/test_viewer.py`:

```python
from browser_support import run_records, step_to


def test_every_beat_of_every_turn_renders(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path, turns=2)))
    for turn in (1, 2):
        for name in ("thinking", "declaring", "resolving", "dispatch"):
            step_to(page, turn, name)
            box = page.locator("#stage").bounding_box()
            assert box["height"] > 200, f"stage collapsed at day {turn}, {name}"


def test_the_map_is_drawn_at_a_real_size(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path)))
    box = page.locator("#boardmap").bounding_box()
    assert box["width"] > 100 and box["height"] > 60


def test_recorded_resolution_is_not_frozen(page, bundle_url, tmp_path):
    """The mockup merged 'auto' and 'freeze', and a recorded run then froze its
    own resolution animation on the first phase."""
    page.goto(bundle_url(run_records(tmp_path)))
    step_to(page, 1, "resolving")
    page.wait_for_timeout(3200)
    assert page.locator(".phase.past").count() == 5


def test_space_freezes_the_scene(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path)))
    step_to(page, 1, "resolving")
    page.keyboard.press(" ")
    page.wait_for_timeout(1500)
    assert page.locator(".phase.past").count() == 0
    assert "frozen" in page.locator("#stage").get_attribute("class")


def test_hover_shows_the_place_card(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path)))
    page.locator("#boardmap [data-place]").first.hover()
    assert page.locator("#tip").is_visible()
    assert "sealed" in page.locator("#tip").inner_text().lower()


def test_card_refreshes_when_the_map_redraws(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path)))
    step_to(page, 1, "thinking")
    page.locator("#boardmap [data-place]").first.hover()
    assert "sealed" in page.locator("#tip").inner_text().lower()
    step_to(page, 1, "declaring")      # the board map redraws under the still pointer
    page.wait_for_timeout(200)
    assert "sealed" not in page.locator("#tip").inner_text().lower()


def test_viewer_truncated_transcript(page, bundle_url, tmp_path):
    records = run_records(tmp_path, turns=2)
    last_state = max(i for i, r in enumerate(records) if r["kind"] == "state")
    page.goto(bundle_url(records[:last_state]))
    step_to(page, 2, "resolving")
    assert page.locator(".banner").is_visible()


def test_viewer_plays_a_scenario_with_an_empty_display_block(page, bundle_url, tmp_path):
    records = run_records(tmp_path, scenario_dir="smoke")
    records[0]["scenario"]["display"] = {}
    for place in records[0]["scenario"]["places"].values():
        place.get("attrs", {}).pop("lat", None)
        place.get("attrs", {}).pop("lon", None)
    page.goto(bundle_url(records))
    for name in ("thinking", "declaring", "resolving", "dispatch"):
        step_to(page, 1, name)
    assert page.locator(".nomap").count() >= 1


def test_presenter_mode_hides_the_controls(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path)))
    page.keyboard.press("p")
    assert not page.locator(".controls").is_visible()
    page.keyboard.press("Escape")
    assert page.locator(".controls").is_visible()
```

`tests/browser/test_app.py`:

```python
def test_the_home_lists_scenarios_and_runs(page, app_url):
    page.goto(app_url)
    page.wait_for_selector("[data-scenario]")
    assert page.locator("[data-scenario]").count() >= 2
    assert page.locator(".runrow").count() == 1


def test_view_opens_the_viewer_on_a_recorded_run(page, app_url):
    page.goto(app_url)
    page.locator(".runrow button").first.click()
    page.wait_for_selector(".visor")
    assert "recorded" in page.locator(".rectag").inner_text().lower()
```

- [ ] **Step 3: Run the browser suite locally**

Run: `uv run playwright install chromium && uv run pytest tests/browser -q`
Expected: PASS. If a test fails, the viewer is wrong, not the test; fix `viewer.js`, `map.js` or `card.js`.

- [ ] **Step 4: Break it on purpose**

Change `if (!V.frozen && !V.done) V.clock += dt;` in `viewer.js` to `if (!V.frozen && !V.done && V.auto) V.clock += dt;` (the mockup's original bug). Run `uv run pytest tests/browser -q -k recorded_resolution`. Expected: FAIL. Revert the change.

- [ ] **Step 5: Run the browser suite in its own pytest process**

Playwright's sync API keeps an event loop running for as long as the session-scoped `browser` fixture lives. Pytest collects `tests/browser/` before `tests/test_*.py`, so in one process every later test that calls `asyncio.run` (every `engine.run`) would fail with `RuntimeError: asyncio.run() cannot be called from a running event loop`. `make test` therefore runs the two suites as two processes. In `Makefile`:

```make
test:
	uv run pytest --ignore=tests/browser
	uv run pytest tests/browser
```

Run: `make test`. Expected: both runs pass (the second skips if Chromium is not installed). Then prove the split matters: run `uv run pytest tests` (one process) and expect `asyncio.run() cannot be called from a running event loop` failures after the browser tests; that is the failure the split prevents.

- [ ] **Step 6: Add Chromium to CI**

In `.github/workflows/tests.yml`, add a step before `make test`:

```yaml
      - run: uv sync --locked
      - run: uv run playwright install --with-deps chromium
```

- [ ] **Step 7: Commit**

```bash
git add tests/browser .github/workflows/tests.yml Makefile
git commit -m "test(browser): the viewer and the shell in real Chromium, in CI"
```

---

### Task 10: Docs, and the acceptance check

**Files:**
- Modify: `README.md` (the "Install and run" section and the module table), `AGENTS.md` ("Where everything lives": `ui/`), `docs/specs/2026-09-28-interface-design.md` (status header)

- [ ] **Step 1: README**

Add `casus serve` to "Install and run", after `casus bundle`:

```bash
uv run casus serve                       # the app on http://127.0.0.1:8321, this machine only
```

Add rows to the module table: `studies.py` ("What is under runs/ and how far each run got"), `server/` ("The local app: the shell, the scenario and run endpoints").

- [ ] **Step 2: AGENTS.md**

Change "Python 3.12+" under "Conventions" to "Python 3.13+". Replace the `ui/` line under "Where everything lives" with:

```markdown
- `ui/` — the viewer and the app: classic scripts under `js/` on one `Casus`
  namespace, `css/app.css`, `app.html` (served by `casus serve`) and
  `bundle.html` (the offline template `casus bundle` fills). No build step.
```

and add under "What done means" a fourth check a person runs:

```markdown
- `uv run casus serve`, open a recorded run, and step through a turn with the
  arrow key: the four beats, the hover card, `P` to present.
```

- [ ] **Step 3: Spec status**

In `docs/specs/2026-09-28-interface-design.md` frontmatter, set `status: "slice 1 implemented (PR #<n>); slices 3-5 pending"`.

- [ ] **Step 4: Acceptance, the way a person does it**

```bash
uv run casus bundle runs/caribbean-v2-repaired-101.jsonl --out /tmp/caribe.html
uv run casus serve
```

Open `/tmp/caribe.html` from the file manager and step through three turns with the arrow key; then open the app, click the same run, and step through the same turns. Both must look the same. Hover a region in the war room, the command post and after resolution. Note in the PR body what was checked and on which run.

- [ ] **Step 5: Commit and open the PR**

```bash
git add README.md AGENTS.md docs/specs/2026-09-28-interface-design.md
git commit -m "docs: the app, the viewer, and how to check them"
git push -u origin 5-slice-1-viewer
gh pr create --title "feat: the game viewer over recorded runs, and casus serve" --body "Part of #5. ..."
```
