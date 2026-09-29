# Slice 3 — live runs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A run starts from **Run** on a scenario card and plays in the viewer while it happens. Beat 1 reads *thinking* until each declaration arrives, a browser that opens late or loses its connection catches up without counting anything twice, and the transcript on disk is the one `casus run` would have written.

**Architecture:** `engine.run_async` gains an `observer` that receives every record after it is in the file. `server/runs.py` holds a `RunManager` that starts runs as asyncio tasks and keeps each run's messages in memory, numbered by `seq`; `subscribe` walks that list and then waits on a condition, so catching up and following live are one loop over one list. `server/sse.py` turns a message iterator into a `text/event-stream` response. `create_app` gains `POST /api/runs` and `GET /api/runs/{id}/events`. In the browser, `shell.js` adds the Run button and the `#/run/<scenario>` route with the setup form, `viewer.js` gains `follow()` (an `EventSource` feeding a `RunModel`) and the live pacing fixes, and `RunModel.push` drops a message whose `seq` it has already seen.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, plain JS, pytest, Playwright (Python) with Chromium. No new dependency: server-sent events are written by hand.

**Specs:** `docs/specs/2026-09-28-interface-design.md`, sections "Live runs", "Pacing", "The server", "Testing". Master plan: `docs/plans/2026-09-29-casus-app-plan.md` (Contracts, Global Constraints, File structure and Review Focus are binding). Slice 1 plan: `docs/plans/2026-09-29-slice-1-viewer.md`; this slice extends its code and reuses its test fixtures.

**Before you start:** slice 1 is merged. Cut `5-slice-3-live-runs` from `origin/main` in `.claude/worktrees/`, run `uv sync --all-extras`, and `uv run playwright install chromium` if the browser suite skips.

## Design decisions

These are the choices the tasks below implement, with the reason for each.

1. **The observer gets a decoded copy of the line just written.** `_Transcript.write` serialises the record, writes and flushes the line, then hands the observer `json.loads(line)`. The copy matters: the `scenario` record holds `scenario.data` itself, so an observer handed the engine's dict could empty the actors mid-run. Decoding the written line also means an observer sees byte for byte what a reader of the file sees, `ts` included. An observer that raises is logged and dropped, and the run goes on.
2. **Every failure ends the transcript with an `error` record.** Today only `RuleFailed` is recorded. A dead endpoint or a failing narrator stops the run with no record, so a browser following it would wait on *thinking* forever and `list_runs` would call it incomplete. Task 2 replaces the two `RuleFailed` handlers with one handler around the turn loop, recording the turn the run was playing. A rule's failure text is unchanged, so existing transcripts and tests keep their bytes.
3. **Live runs are served from memory, not by tailing the file.** Reading the file and then joining a live queue has a gap: a record written between the read and the join is lost, or seen twice if you over-correct. Here the run's messages are one in-memory list filled by the observer. A subscriber copies what is there under a lock, yields it, and waits on the same lock's condition for more. Only one coroutine runs at a time, so nothing falls between the two phases. The list is the transcript record for record, because the observer is fed from the written line. The file is read only for runs that are not in memory, which are runs from before this server started and are therefore over.
4. **The stream carries `ledger` records, not raw `mutation` records.** `RunModel.push` handles both, but the stream applies the `bundle.viewer_records` transformation, one record at a time (`LedgerFold`). Three reasons: a finished run then streams exactly the list `GET /api/runs/{id}` returns, which the spec asks for ("indistinguishable from a recorded one") and which one test can check; the viewer reads live and recorded runs through the same `ledger` branch of `RunModel.push`, so there is one code path to get right; and the ledger stays out of the browser, as it does in the bundle. The one deliberate difference from `viewer_records`: a count still open when the run ends or fails goes out just before the `end` or `error`, so the terminal record is always the last message and a subscriber can stop there. For an engine-written complete run the two are identical, and Task 4 tests that.
5. **Every message carries `seq`, twice guarded.** The server numbers messages from 0 and sends the number as the SSE `id:`. A browser that reconnects on its own sends `Last-Event-ID` and the server resumes after it (`subscribe(run_id, after=n)`). When the page reopens the stream itself it starts from 0, and `RunModel.push` drops any `seq` it has already seen. That second guard is what the reconnect browser test exercises.
6. **The form's model replaces every actor's model, in the data the transcript records.** Every actor in a valid scenario names a model, so a "default model" can only mean "the model this run plays on". Building engines for another model while the `scenario` and `prompt` records still named the old one would make the transcript lie. So `RunManager` rewrites the actors' `model` in a copy of the scenario data (`dataclasses.replace`) before the run starts. The narrator follows the CLI: `scenario.narrator_model()`, else the first actor's model, which is now the chosen one. An empty field keeps the scenario's own models.
7. **The live viewer mounts on the stream's first message.** `Casus.viewer.mount` reads the actors, the language and the header when it is called. Mounted on an empty `RunModel` it would draw no panes. The run route mounts it when the `scenario` record arrives, which is always `seq` 0.

## Global Constraints

Everything in the master plan's Global Constraints, plus:

- The observer watches; it cannot change a run. A transcript written with an observer is byte-identical to one written without.
- A finished run's event stream, with `seq` removed, equals `bundle.viewer_records` of its transcript.
- No new dependency. `sse.py` uses FastAPI's `StreamingResponse` only.
- asyncio tests follow the repo: plain test functions that call `asyncio.run(...)`. No pytest-asyncio.
- The file a live run writes is `runs/<scenario>-<seed>.jsonl`, then `-2`, `-3`… when that name is taken. A run never overwrites another.

## Review Focus

Owned by this slice (from the master plan):

2. A browser that subscribes after the run finished, or reconnects mid-run, receives every record exactly once, in order — `tests/test_server.py::test_late_and_reconnecting_subscribers_get_each_record_once`, and in a real browser `tests/browser/test_viewer.py::test_live_reconnect_counts_nothing_twice`.

Also pinned here because this slice owns the code:

- An observer that mutates the dict it receives changes nothing — `tests/test_observer.py::test_an_observer_that_changes_what_it_receives_changes_nothing`.
- Two starts on the same seed in the same moment get two files and leave an older run alone — `tests/test_server.py::test_a_second_start_on_the_same_seed_never_overwrites`.
- A dead endpoint is recorded as an error on the turn it stopped — `tests/test_engine.py::test_an_endpoint_that_fails_is_recorded_and_the_run_stops`.
- A presenter who presses on cannot reach the command post before the turn has resolved — `tests/browser/test_viewer.py::test_live_command_post_waits_for_the_turn_to_resolve`.

---

### Task 1: The observer in `engine.run_async`

**Files:**
- Modify: `src/casus/engine.py` (imports, `_Transcript`, `run_async`, `_write_state`, `_write_declaration`)
- Modify: `tests/helpers.py` (add `RAIDING`, `Gate`, `LiveEngine`)
- Create: `tests/test_observer.py`

**Interfaces:**
- Consumes: `engine.run(scenario, **kwargs)` (passes kwargs to `run_async`), `engine.read_records(path)`.
- Produces: `engine.Observer = Callable[[dict], Awaitable[None]]`; `async def run_async(scenario, seed=1, out=None, engines=None, narrator_engine=None, turns=None, observer: Observer | None = None) -> RunSummary` (master plan contract). In `tests/helpers.py`: `RAIDING` (a reply function), `Gate()` with `.open(calls: int)`, `async .passage()`, `async .until_arrived(calls: int, timeout=5.0)`, `.arrived: int`; `LiveEngine(reply=None, delay: float = 0.0, gate: Gate | None = None)`, a `FakeEngine` that also answers the narrator.

- [ ] **Step 1: Add the test engines to `tests/helpers.py`**

Add `import asyncio` to the imports at the top, then append:

```python
#: Blue raids the border every turn on smoke, so every turn has events and the
#: narrator is asked something.
RAIDING = scripted(
    {
        "BLUE": {
            "actions": [{"type": "raid", "place": "border", "intensity": 3}],
            "rationale": "push",
            "assessment": "they hold",
        }
    }
)


class Gate:
    """Holds player calls until a test lets them through, so a test can stop a
    live run at a known point instead of sleeping and hoping. `arrived` counts
    the calls that have reached the gate, whether or not they have passed."""

    def __init__(self) -> None:
        self._slots = asyncio.Semaphore(0)
        self.arrived = 0

    def open(self, calls: int) -> None:
        for _ in range(calls):
            self._slots.release()

    async def passage(self) -> None:
        self.arrived += 1
        await self._slots.acquire()

    async def until_arrived(self, calls: int, timeout: float = 5.0) -> None:
        async with asyncio.timeout(timeout):
            while self.arrived < calls:
                await asyncio.sleep(0.001)


class LiveEngine(FakeEngine):
    """A FakeEngine for live runs, where one factory makes the players and the
    narrator. It answers the narrator's dispatch with as many predicates as the
    schema asks for. `delay` makes every answer take that long, so records reach
    an observer over time; `gate` holds player calls until the test opens it."""

    def __init__(self, reply=None, delay: float = 0.0, gate: Gate | None = None):
        super().__init__(reply)
        self.delay = delay
        self.gate = gate

    async def create(self, context, schema, *instructions):
        if self.delay:
            await asyncio.sleep(self.delay)
        wanted = schema.model_json_schema().get("properties", {}).get("predicates")
        if wanted is not None:
            return schema.model_validate({"predicates": ["acted"] * wanted["minItems"]})
        if self.gate is not None:
            await self.gate.passage()
        return await super().create(context, schema, *instructions)
```

`scripted` is defined above in the same file, so `RAIDING` must come after it; append everything at the end of the file.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_observer.py`:

```python
"""The observer watches a run as it is written. It cannot change the run."""

import json

import pytest
from scenariopaths import SCENARIOS

from casus import engine
from casus.scenario import Scenario
from helpers import RAIDING, FakeEngine, LiveEngine

SMOKE = SCENARIOS / "smoke"


@pytest.fixture
def frozen_clock(monkeypatch):
    """Every record carries a `ts`. Two runs can match byte for byte only if
    they read the same clock."""
    monkeypatch.setattr(engine.time, "time", lambda: 1_790_000_000.0)


def _play(out=None, observer=None, turns=2, reply=RAIDING, scenario=None):
    scenario = scenario or Scenario.load(SMOKE)
    return engine.run(
        scenario,
        seed=11,
        out=out,
        turns=turns,
        observer=observer,
        engines={a: FakeEngine(reply) for a in scenario.actors},
        narrator_engine=LiveEngine(),
    )


def _watcher(seen: list):
    async def watch(record: dict) -> None:
        seen.append(record)

    return watch


def test_a_run_with_an_observer_writes_the_same_bytes_as_one_without(tmp_path, frozen_clock):
    seen: list[dict] = []
    _play(tmp_path / "plain.jsonl")
    _play(tmp_path / "watched.jsonl", observer=_watcher(seen))
    assert seen
    assert (tmp_path / "watched.jsonl").read_bytes() == (tmp_path / "plain.jsonl").read_bytes()


def test_the_observer_sees_every_record_in_the_order_it_was_written(tmp_path):
    seen: list[dict] = []
    out = tmp_path / "run.jsonl"
    _play(out, observer=_watcher(seen))
    assert seen == engine.read_records(out)


def test_each_record_is_in_the_file_before_the_observer_sees_it(tmp_path):
    out = tmp_path / "run.jsonl"
    last_lines: list[dict] = []

    async def watch(record: dict) -> None:
        last_lines.append(json.loads(out.read_text(encoding="utf-8").splitlines()[-1]))

    _play(out, observer=watch)
    assert last_lines == engine.read_records(out)


def test_records_reach_the_observer_while_the_run_is_going(tmp_path):
    """Not at the end: the first player is asked only after the observer has
    seen the header, the opening state and every prompt of turn 1."""
    scenario = Scenario.load(SMOKE)
    seen: list[str] = []
    seen_when_asked: list[list[str]] = []

    async def watch(record: dict) -> None:
        seen.append(record["kind"])

    def reply(prompt: str) -> dict:
        seen_when_asked.append(list(seen))
        return RAIDING(prompt)

    _play(tmp_path / "run.jsonl", observer=watch, turns=1, reply=reply, scenario=scenario)
    assert seen_when_asked[0] == ["scenario", "state", *["prompt"] * len(scenario.actors)]


def test_an_observer_that_changes_what_it_receives_changes_nothing(tmp_path, frozen_clock):
    """It gets a copy decoded from the line just written. Handed the engine's
    own dict, clearing the scenario record would empty the scenario's actors and
    the run would fail on the next model lookup."""

    async def vandal(record: dict) -> None:
        for value in record.values():
            if isinstance(value, dict):
                value.clear()
        record.clear()

    _play(tmp_path / "plain.jsonl")
    _play(tmp_path / "vandalised.jsonl", observer=vandal)
    vandalised = (tmp_path / "vandalised.jsonl").read_bytes()
    assert vandalised == (tmp_path / "plain.jsonl").read_bytes()


def test_an_observer_that_raises_is_dropped_and_the_run_goes_on(tmp_path, frozen_clock, caplog):
    calls: list[str] = []

    async def broken(record: dict) -> None:
        calls.append(record["kind"])
        if len(calls) == 3:
            raise RuntimeError("the browser went away")

    _play(tmp_path / "plain.jsonl")
    _play(tmp_path / "watched.jsonl", observer=broken)
    assert len(calls) == 3
    assert (tmp_path / "watched.jsonl").read_bytes() == (tmp_path / "plain.jsonl").read_bytes()
    assert "observer" in caplog.text


def test_the_observer_sees_the_error_that_stopped_a_run(tmp_path):
    base = Scenario.load(SMOKE)
    rule = "\n\n@rule(phase='contest')\ndef broken(s):\n    s.place('atlantis')\n"
    broken = Scenario.from_parts(base.data, base.rules_source + rule)
    seen: list[dict] = []
    with pytest.raises(engine.RuleFailed):
        _play(tmp_path / "run.jsonl", observer=_watcher(seen), scenario=broken)
    assert seen[-1]["kind"] == "error"
    assert "atlantis" in seen[-1]["error"]
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_observer.py -q`
Expected: FAIL with `TypeError: run_async() got an unexpected keyword argument 'observer'`.

- [ ] **Step 4: Implement**

In `src/casus/engine.py`, change the imports and add the logger and the type:

```python
import asyncio
import dataclasses
import json
import logging
import pathlib
import random
import time
from collections.abc import Awaitable, Callable, Iterator
```

After the imports from `.state`, before `__all__`:

```python
log = logging.getLogger(__name__)

#: What `run_async` hands every record to, once the record is in the file.
Observer = Callable[[dict], Awaitable[None]]
```

and add `"Observer"` to `__all__`.

Replace the `_Transcript` class with:

```python
class _Transcript:
    """Append-only JSONL writer. Flushes every record, so a run killed halfway
    still replays up to the last completed turn.

    An observer, when given, receives each record after it is in the file,
    decoded from the line just written. It is a copy, so nothing the observer
    does to it reaches the run, and it is exactly what a reader of the file will
    see. An observer that raises is dropped with a warning and the run goes on.
    """

    def __init__(self, path: pathlib.Path | None, observer: Observer | None = None):
        self.path = path
        self._fh = None
        self._observer = observer
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = path.open("w", encoding="utf-8")

    async def write(self, record: dict) -> None:
        assert record["kind"] in RECORD_KINDS, f"unknown record kind {record['kind']!r}"
        record.setdefault("ts", time.time())
        line = json.dumps(record, ensure_ascii=False)
        if self._fh is not None:
            self._fh.write(line + "\n")
            self._fh.flush()
        if self._observer is not None:
            try:
                await self._observer(json.loads(line))
            except Exception:
                log.warning("the run observer raised and was dropped", exc_info=True)
                self._observer = None

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
```

Replace `run_async` with:

```python
async def run_async(
    scenario: Scenario,
    seed: int = 1,
    out: pathlib.Path | str | None = None,
    engines: dict[str, Engine] | None = None,
    narrator_engine: Engine | None = None,
    turns: int | None = None,
    observer: Observer | None = None,
) -> RunSummary:
    """Play the scenario and write a transcript.

    `observer`, when given, receives every record once it is in the file, in the
    order written. It watches; nothing it does reaches the run.
    """
    transcript = _Transcript(pathlib.Path(out) if out is not None else None, observer)
    rng = random.Random(seed)
    state = scenario.initial_state()
    total_turns = turns if turns is not None else scenario.turns

    engines = engines or {a: engine_for(scenario.model(a)) for a in scenario.actors}
    players = {
        a: Player(actor_id=a, scenario=scenario, engine=engines[a]) for a in scenario.actors
    }
    summary = RunSummary(
        scenario=scenario.name, seed=seed, turns=0, states=[state], transcript=transcript.path
    )
    await transcript.write(
        {
            "kind": "scenario",
            "turn": 0,
            "seed": seed,
            "turns": total_turns,
            "name": scenario.name,
            "language": scenario.language(),
            # The data and the rules both travel inside the transcript, so a
            # replay needs nothing but this one file.
            "scenario": scenario.data,
            "rules_source": scenario.rules_source,
        }
    )
    await _write_state(transcript, state)

    try:
        for _ in range(total_turns):
            order = sorted(players)
            # Draws first, in a fixed order: this is where determinism lives.
            try:
                views = {a: players[a].view(state, rng) for a in order}
            except RuleFailed as exc:
                await transcript.write({"kind": "error", "turn": state.turn, "error": str(exc)})
                raise
            for actor_id in order:
                prompt, offered = views[actor_id]
                await transcript.write(
                    {
                        "kind": "prompt",
                        "turn": state.turn,
                        "actor": actor_id,
                        "model": players[actor_id].model,
                        "prompt": prompt,
                        "offered": {k: list(v) if v else None for k, v in offered.items()},
                    }
                )

            results = await asyncio.gather(
                *(players[a].decide(state, *views[a]) for a in order)
            )
            declared: list[Action] = []
            for actor_id, player_turn in zip(order, results, strict=True):
                declared.extend(player_turn.actions)
                await _write_declaration(transcript, state.turn, actor_id, player_turn)

            turn = state.turn
            try:
                state, events, mutations = _resolve(scenario, state, declared, rng)
            except RuleFailed as exc:
                await transcript.write({"kind": "error", "turn": turn, "error": str(exc)})
                raise
            for event in events:
                await transcript.write(
                    {"kind": "event", "turn": turn, "event": event.to_json()}
                )
            for mutation in mutations:
                await transcript.write({"kind": "mutation", **mutation.to_json()})
            if narrator_engine is not None:
                text = await narrator.narrate(state, events, narrator_engine, scenario)
                await transcript.write({"kind": "narrative", "turn": turn, "text": text})

            await _write_state(transcript, state)
            summary.states.append(state)
            summary.turns += 1

        await transcript.write({"kind": "end", "turn": state.turn})
    finally:
        transcript.close()
    return summary
```

Replace `_write_state` and `_write_declaration` with their async versions:

```python
async def _write_state(transcript: _Transcript, state: WorldState) -> None:
    await transcript.write(
        {
            "kind": "state",
            "turn": state.turn,
            "digest": state.digest(),
            "state": state.to_json(),
        }
    )


async def _write_declaration(
    transcript: _Transcript, turn: int, actor_id: str, player_turn: PlayerTurn
) -> None:
    await transcript.write(
        {
            "kind": "declaration",
            "turn": turn,
            "actor": actor_id,
            "model": player_turn.model,
            "declaration": player_turn.declaration,
        }
    )
    for action in player_turn.actions:
        await transcript.write(
            {
                "kind": "action",
                "turn": turn,
                "actor": actor_id,
                "action": action.to_json(),
                "rationale": player_turn.rationale,
                "assessment": player_turn.assessment,
                "prompt": player_turn.prompt,
            }
        )
```

Nothing else calls `_Transcript`, `_write_state` or `_write_declaration`; check with `grep -rn "_Transcript\|_write_state\|_write_declaration" src tests`.

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_observer.py tests/test_engine.py tests/test_bundle.py tests/test_studies.py -q`
Expected: PASS. `test_engine.py` and the others prove the transcript did not change for runs without an observer.

- [ ] **Step 6: Break it on purpose**

In `_Transcript.write`, change `await self._observer(json.loads(line))` to `await self._observer(record)`. Run `uv run pytest tests/test_observer.py -q -k changes_what_it_receives`. Expected: FAIL (the vandal empties `scenario.data` and the run dies). Revert.

- [ ] **Step 7: Commit**

```bash
git add src/casus/engine.py tests/helpers.py tests/test_observer.py
git commit -m "feat(engine): an observer that sees every record once it is written"
```

---

### Task 2: Every failure ends the transcript with an error

**Files:**
- Modify: `src/casus/engine.py` (`run_async`, new `_error_text`)
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `run_async` from Task 1.
- Produces: any exception raised inside the turn loop is written as `{"kind": "error", "turn": <turn being played>, "error": <text>}` and re-raised. For `RuleFailed` the text is `str(exc)` as today; for anything else it is `"<TypeName>: <message>"`, or the type name when the message is empty.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py`:

```python
class _Unreachable(FakeEngine):
    async def create(self, context, schema, *instructions):
        raise ConnectionError("endpoint unreachable")


def test_an_endpoint_that_fails_is_recorded_and_the_run_stops(tmp_path):
    """Live, a browser learns that a run died from its last record. A rule's
    failure was recorded; a dead endpoint was not, and the run just stopped."""
    scenario = _smoke()
    out = tmp_path / "run.jsonl"
    with pytest.raises(ConnectionError):
        engine.run(
            scenario,
            seed=1,
            out=out,
            engines={a: _Unreachable() for a in scenario.actors},
            turns=2,
        )
    error = _records(out)[-1]
    assert (error["kind"], error["turn"]) == ("error", 1)
    assert "ConnectionError" in error["error"] and "unreachable" in error["error"]


def test_a_narrator_that_fails_is_recorded_against_the_turn_it_was_narrating(tmp_path):
    """The narrator runs after the rules have moved the world to the next turn;
    the failure still belongs to the turn it was writing about."""
    out = tmp_path / "run.jsonl"
    with pytest.raises(ConnectionError):
        _run(out, turns=2, narrator_engine=_Unreachable())
    error = _records(out)[-1]
    assert (error["kind"], error["turn"]) == ("error", 1)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_engine.py -q -k "endpoint_that_fails or narrator_that_fails"`
Expected: FAIL; the last record is a `prompt` or a `mutation`, not an `error`.

- [ ] **Step 3: Implement**

In `src/casus/engine.py`, add after `engine_for`:

```python
def _error_text(exc: Exception) -> str:
    """A rule's failure reads as the rule reported it. Anything else is named by
    its type too, because `str()` of a timeout or a dropped connection may be
    empty."""
    if isinstance(exc, RuleFailed):
        return str(exc)
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
```

Replace `run_async` with this version. The two `RuleFailed` handlers become one handler around the loop, and `turn` is set at the top of each turn so a narrator failure is recorded on the turn it was narrating:

```python
async def run_async(
    scenario: Scenario,
    seed: int = 1,
    out: pathlib.Path | str | None = None,
    engines: dict[str, Engine] | None = None,
    narrator_engine: Engine | None = None,
    turns: int | None = None,
    observer: Observer | None = None,
) -> RunSummary:
    """Play the scenario and write a transcript.

    `observer`, when given, receives every record once it is in the file, in the
    order written. It watches; nothing it does reaches the run.
    """
    transcript = _Transcript(pathlib.Path(out) if out is not None else None, observer)
    rng = random.Random(seed)
    state = scenario.initial_state()
    total_turns = turns if turns is not None else scenario.turns

    engines = engines or {a: engine_for(scenario.model(a)) for a in scenario.actors}
    players = {
        a: Player(actor_id=a, scenario=scenario, engine=engines[a]) for a in scenario.actors
    }
    summary = RunSummary(
        scenario=scenario.name, seed=seed, turns=0, states=[state], transcript=transcript.path
    )
    await transcript.write(
        {
            "kind": "scenario",
            "turn": 0,
            "seed": seed,
            "turns": total_turns,
            "name": scenario.name,
            "language": scenario.language(),
            # The data and the rules both travel inside the transcript, so a
            # replay needs nothing but this one file.
            "scenario": scenario.data,
            "rules_source": scenario.rules_source,
        }
    )
    await _write_state(transcript, state)

    turn = state.turn
    try:
        for _ in range(total_turns):
            turn = state.turn
            order = sorted(players)
            # Draws first, in a fixed order: this is where determinism lives.
            views = {a: players[a].view(state, rng) for a in order}
            for actor_id in order:
                prompt, offered = views[actor_id]
                await transcript.write(
                    {
                        "kind": "prompt",
                        "turn": state.turn,
                        "actor": actor_id,
                        "model": players[actor_id].model,
                        "prompt": prompt,
                        "offered": {k: list(v) if v else None for k, v in offered.items()},
                    }
                )

            results = await asyncio.gather(
                *(players[a].decide(state, *views[a]) for a in order)
            )
            declared: list[Action] = []
            for actor_id, player_turn in zip(order, results, strict=True):
                declared.extend(player_turn.actions)
                await _write_declaration(transcript, state.turn, actor_id, player_turn)

            state, events, mutations = _resolve(scenario, state, declared, rng)
            for event in events:
                await transcript.write(
                    {"kind": "event", "turn": turn, "event": event.to_json()}
                )
            for mutation in mutations:
                await transcript.write({"kind": "mutation", **mutation.to_json()})
            if narrator_engine is not None:
                text = await narrator.narrate(state, events, narrator_engine, scenario)
                await transcript.write({"kind": "narrative", "turn": turn, "text": text})

            await _write_state(transcript, state)
            summary.states.append(state)
            summary.turns += 1

        await transcript.write({"kind": "end", "turn": state.turn})
    except Exception as exc:
        # A rule, a hook, a player's endpoint or the narrator's: whatever stopped
        # the run is its last record, on the turn it was playing, so a reader of
        # the transcript, or a browser following it live, learns why it ends here.
        await transcript.write({"kind": "error", "turn": turn, "error": _error_text(exc)})
        raise
    finally:
        transcript.close()
    return summary
```

`KeyboardInterrupt` and `asyncio.CancelledError` are not `Exception`, so a run that is interrupted or cancelled still ends without a record and reads as incomplete, which is what it is.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_engine.py tests/test_observer.py tests/test_studies.py -q`
Expected: PASS, including the existing `test_a_rule_that_raises_is_recorded_and_the_run_stops` and `test_a_hook_that_raises_is_recorded_naming_the_hook`, which each still find exactly one error record.

- [ ] **Step 5: Commit**

```bash
git add src/casus/engine.py tests/test_engine.py
git commit -m "fix(engine): record any failure that stops a run, not only a rule's"
```

---

### Task 3: The event-stream helper (`server/sse.py`)

**Files:**
- Create: `src/casus/server/sse.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `sse.KEEPALIVE: bytes`, `sse.CLOSE: bytes`, `sse.format_event(message: dict, *, event_id: int | None = None) -> bytes`, `async def sse.frames(messages: AsyncIterable[dict], *, keepalive: float = 15.0) -> AsyncIterator[bytes]`, `sse.event_stream(messages: AsyncIterable[dict], *, keepalive: float = 15.0) -> StreamingResponse`. `frames` uses a message's `seq`, when it has one, as the event id.

- [ ] **Step 1: Write the failing tests**

Add `import asyncio` to the imports of `tests/test_server.py`, and `from casus.server import sse` next to `from casus.server.app import create_app`. Append:

```python
# --- the event stream ---------------------------------------------------------


async def _frames(stream) -> list[bytes]:
    async with asyncio.timeout(5):
        return [frame async for frame in stream]


def test_an_event_is_one_data_line_with_its_id():
    """JSON escapes every newline, so a message with a line break in its text
    is still one `data:` line, which is all the browser reads."""
    frame = sse.format_event({"kind": "narrative", "text": "two\nlines"}, event_id=3)
    assert frame == b'id: 3\ndata: {"kind": "narrative", "text": "two\\nlines"}\n\n'


def test_a_stream_is_its_messages_in_order_then_a_close_event():
    async def messages():
        yield {"kind": "state", "seq": 0}
        yield {"kind": "end", "seq": 1}

    frames = asyncio.run(_frames(sse.frames(messages())))
    assert frames == [
        sse.format_event({"kind": "state", "seq": 0}, event_id=0),
        sse.format_event({"kind": "end", "seq": 1}, event_id=1),
        sse.CLOSE,
    ]


def test_a_quiet_stream_sends_keepalive_comments_and_loses_nothing():
    async def slow():
        await asyncio.sleep(0.2)
        yield {"kind": "end", "seq": 0}

    frames = asyncio.run(_frames(sse.frames(slow(), keepalive=0.05)))
    assert frames[0] == sse.KEEPALIVE
    assert frames[-2:] == [sse.format_event({"kind": "end", "seq": 0}, event_id=0), sse.CLOSE]


def test_closing_the_stream_early_cancels_its_wait():
    """A browser that goes away must not leave a subscriber waiting forever."""

    async def play() -> bool:
        cancelled = asyncio.Event()

        async def forever():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            yield {}

        stream = sse.frames(forever(), keepalive=0.01)
        assert await anext(stream) == sse.KEEPALIVE
        await stream.aclose()
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        return cancelled.is_set()

    assert asyncio.run(play())


def test_the_response_is_an_uncached_event_stream():
    async def nothing():
        return
        yield

    response = sse.event_stream(nothing())
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_server.py -q -k "event or stream"`
Expected: FAIL with `ImportError: cannot import name 'sse' from 'casus.server'`.

- [ ] **Step 3: Implement**

Create `src/casus/server/sse.py`:

```python
"""Server-sent events without a library: one `data:` line of JSON per message.

Each message's `seq` goes out as the event id, so a browser that reconnects on
its own sends `Last-Event-ID` and the server can resume after it. A comment line
goes out after a stretch of silence, so the connection stays open through a slow
turn. The last frame is a `close` event: it tells the browser the stream is over,
not dropped, so it does not reconnect.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterable, AsyncIterator

from fastapi.responses import StreamingResponse

KEEPALIVE = b": keepalive\n\n"
CLOSE = b"event: close\ndata: {}\n\n"
KEEPALIVE_SECONDS = 15.0

_END = object()


def format_event(message: dict, *, event_id: int | None = None) -> bytes:
    """One event. JSON escapes every newline, so the payload is a single line."""
    head = f"id: {event_id}\n" if event_id is not None else ""
    return (head + "data: " + json.dumps(message, ensure_ascii=False) + "\n\n").encode()


async def _next(messages: AsyncIterator[dict]):
    try:
        return await anext(messages)
    except StopAsyncIteration:
        return _END


async def frames(
    messages: AsyncIterable[dict], *, keepalive: float = KEEPALIVE_SECONDS
) -> AsyncIterator[bytes]:
    """The bytes of the stream: each message as an event, a keepalive comment
    after `keepalive` seconds with nothing to send, and `CLOSE` at the end.

    The wait for the next message is a task that outlives a keepalive. Cancelling
    it on every timeout would cancel the subscriber's own wait and end it.
    """
    source = aiter(messages)
    waiting: asyncio.Task | None = None
    try:
        while True:
            if waiting is None:
                waiting = asyncio.create_task(_next(source))
            done, _ = await asyncio.wait({waiting}, timeout=keepalive)
            if not done:
                yield KEEPALIVE
                continue
            message, waiting = waiting.result(), None
            if message is _END:
                break
            yield format_event(message, event_id=message.get("seq"))
        yield CLOSE
    finally:
        if waiting is not None:
            waiting.cancel()


def event_stream(
    messages: AsyncIterable[dict], *, keepalive: float = KEEPALIVE_SECONDS
) -> StreamingResponse:
    return StreamingResponse(
        frames(messages, keepalive=keepalive),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_server.py -q`
Expected: PASS, the slice 1 server tests and the five new ones.

- [ ] **Step 5: Commit**

```bash
git add src/casus/server/sse.py tests/test_server.py
git commit -m "feat(server): server-sent events by hand, with keepalives and a close event"
```

---

### Task 4: The run manager (`server/runs.py`)

**Files:**
- Create: `src/casus/server/runs.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `engine.run_async(..., observer=...)` (Task 1), `engine.engine_for`, `bundle.KEPT_KINDS`, `Scenario.load`.
- Produces: `RunManager(runs_dir: pathlib.Path, engine_factory: Callable[[str], Engine] = engine_for)`; `async RunManager.start(scenario_dir: pathlib.Path, *, seed: int, turns: int | None, model: str | None) -> str` (raises `ScenarioError` before writing anything); `RunManager.subscribe(run_id: str, after: int = -1) -> AsyncIterator[dict]` (raises `KeyError` for an unknown run). Every message is a viewer record plus `"seq": int`, numbered from 0. `LedgerFold` with `.feed(record) -> list[dict]` and `.flush() -> list[dict]`.
- The factory is called once per actor, in the scenario's actor order, with that actor's model, then once for the narrator with `scenario.narrator_model() or scenario.model(first actor)`, as `casus run` does.

- [ ] **Step 1: Write the failing tests**

Add to the imports of `tests/test_server.py`: `from casus import bundle` (next to `engine`), `from casus.server.runs import RunManager`, and extend the helpers import to `from helpers import RAIDING, FakeEngine, Gate, LiveEngine`. Append:

```python
# --- live runs ------------------------------------------------------------------

SMOKE = SCENARIOS / "smoke"


def _live(**kwargs):
    return lambda model: LiveEngine(RAIDING, **kwargs)


class _Unreachable(FakeEngine):
    async def create(self, context, schema, *instructions):
        raise ConnectionError("endpoint unreachable")


async def _collect(stream) -> list[dict]:
    async with asyncio.timeout(10):
        return [message async for message in stream]


def _plain(messages: list[dict]) -> list[dict]:
    return [{k: v for k, v in m.items() if k != "seq"} for m in messages]


def test_a_live_run_streams_exactly_its_viewer_records(tmp_path):
    async def play():
        manager = RunManager(tmp_path, engine_factory=_live())
        run_id = await manager.start(SMOKE, seed=2, turns=2, model=None)
        return run_id, await _collect(manager.subscribe(run_id))

    run_id, messages = asyncio.run(play())
    assert run_id == "smoke-2"
    expected = bundle.viewer_records(engine.read_records(tmp_path / "smoke-2.jsonl"))
    assert _plain(messages) == expected
    assert [m["seq"] for m in messages] == list(range(len(expected)))
    assert any(m["kind"] == "ledger" for m in messages)
    assert messages[-1]["kind"] == "end"


def test_a_restarted_server_serves_the_same_numbered_stream_from_the_file(tmp_path):
    async def play():
        first = RunManager(tmp_path, engine_factory=_live())
        run_id = await first.start(SMOKE, seed=2, turns=2, model=None)
        live = await _collect(first.subscribe(run_id))
        restarted = RunManager(tmp_path, engine_factory=_live())
        from_file = await _collect(restarted.subscribe(run_id))
        resumed = await _collect(restarted.subscribe(run_id, after=4))
        return live, from_file, resumed

    live, from_file, resumed = asyncio.run(play())
    assert from_file == live
    assert resumed == live[5:]


def test_late_and_reconnecting_subscribers_get_each_record_once(tmp_path):
    """Review Focus 2. One subscriber watches from the start. One takes three
    messages, drops, and comes back mid-run with the last number it saw. One
    arrives after the run is over. Each gets every message once, in order."""
    players = len(Scenario.load(SMOKE, validate=False).actors)

    async def play():
        gate = Gate()
        manager = RunManager(
            tmp_path, engine_factory=lambda model: LiveEngine(RAIDING, gate=gate)
        )
        run_id = await manager.start(SMOKE, seed=3, turns=2, model=None)
        early = asyncio.create_task(_collect(manager.subscribe(run_id)))

        await gate.until_arrived(players)  # turn 1's prompts are out
        dropped: list[dict] = []
        stream = manager.subscribe(run_id)
        async for message in stream:
            dropped.append(message)
            if len(dropped) == 3:
                break
        await stream.aclose()

        gate.open(players)
        await gate.until_arrived(2 * players)  # turn 2's prompts are out
        resumed = asyncio.create_task(
            _collect(manager.subscribe(run_id, after=dropped[-1]["seq"]))
        )
        await asyncio.sleep(0.05)
        following_live = not resumed.done()
        gate.open(players)
        everything = await early
        late = await _collect(manager.subscribe(run_id))
        return run_id, everything, dropped + await resumed, late, following_live

    run_id, everything, reconnected, late, following_live = asyncio.run(play())
    expected = bundle.viewer_records(engine.read_records(tmp_path / f"{run_id}.jsonl"))
    assert following_live, "the reconnected subscriber should have been waiting on the run"
    assert [m["seq"] for m in everything] == list(range(len(expected)))
    for stream in (everything, reconnected, late):
        assert _plain(stream) == expected


def test_a_second_start_on_the_same_seed_never_overwrites(tmp_path):
    (tmp_path / "smoke-4.jsonl").write_text("an older run\n")

    async def play():
        manager = RunManager(tmp_path, engine_factory=_live())
        starts = [manager.start(SMOKE, seed=4, turns=1, model=None) for _ in range(2)]
        ids = await asyncio.gather(*starts)
        for run_id in ids:
            await _collect(manager.subscribe(run_id))
        return ids

    assert sorted(asyncio.run(play())) == ["smoke-4-2", "smoke-4-3"]
    assert (tmp_path / "smoke-4.jsonl").read_text() == "an older run\n"


def test_a_live_run_narrates_like_the_cli(tmp_path):
    scenario = Scenario.load(SMOKE, validate=False)
    asked: list[str] = []

    def factory(model: str):
        asked.append(model)
        return LiveEngine(RAIDING)

    async def play():
        manager = RunManager(tmp_path, engine_factory=factory)
        run_id = await manager.start(SMOKE, seed=1, turns=1, model=None)
        return await _collect(manager.subscribe(run_id))

    messages = asyncio.run(play())
    first = next(iter(scenario.actors))
    narrator_model = scenario.narrator_model() or scenario.model(first)
    assert asked == [*(scenario.model(a) for a in scenario.actors), narrator_model]
    assert any(m["kind"] == "narrative" and m["text"] for m in messages)


def test_the_model_chosen_for_a_run_is_the_one_its_transcript_records(tmp_path):
    asked: list[str] = []

    def factory(model: str):
        asked.append(model)
        return LiveEngine(RAIDING)

    async def play():
        manager = RunManager(tmp_path, engine_factory=factory)
        run_id = await manager.start(SMOKE, seed=1, turns=1, model="local/tiny-7b")
        await _collect(manager.subscribe(run_id))
        return run_id

    records = engine.read_records(tmp_path / f"{asyncio.run(play())}.jsonl")
    assert set(asked) == {"local/tiny-7b"}
    assert {r["model"] for r in records if r["kind"] == "prompt"} == {"local/tiny-7b"}
    actors = records[0]["scenario"]["actors"].values()
    assert {spec["model"] for spec in actors} == {"local/tiny-7b"}


def test_a_run_whose_endpoint_dies_ends_its_stream_with_the_error(tmp_path):
    async def play():
        manager = RunManager(tmp_path, engine_factory=lambda model: _Unreachable())
        run_id = await manager.start(SMOKE, seed=1, turns=2, model=None)
        return await _collect(manager.subscribe(run_id))

    messages = asyncio.run(play())
    assert messages[-1]["kind"] == "error"
    assert "unreachable" in messages[-1]["error"]


def test_an_unknown_run_cannot_be_subscribed(tmp_path):
    async def play():
        await _collect(RunManager(tmp_path).subscribe("nope"))

    with pytest.raises(KeyError):
        asyncio.run(play())
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_server.py -q -k "live or subscrib or start or narrates or model_chosen or endpoint_dies"`
Expected: FAIL with `ModuleNotFoundError: No module named 'casus.server.runs'`.

- [ ] **Step 3: Implement**

Create `src/casus/server/runs.py`:

```python
"""Live runs: start one in the background and let any number of browsers follow it.

Every message a run started by this server has produced is kept in memory, in
order, numbered from 0 (`seq`). A subscriber walks that list from where it starts
and waits on a condition at its end. What was already there and what comes next
are the same list, and one coroutine runs at a time, so there is no moment between
catching up and following live in which a record can be missed or seen twice. The
list matches the transcript record for record: the engine's observer hands over
each record decoded from the line it has just written.

The file is read only for runs that are not in memory. Those are runs from before
this server started, so they are over, finished or dead, and the file is all of
them.

The stream carries what `bundle.viewer_records` makes of a transcript: the kinds
the viewer reads, and one `ledger` count per turn in place of that turn's
`mutation` records. A finished run therefore streams what `GET /api/runs/{id}`
returns, and the viewer reads live and recorded runs through the same code.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import pathlib
import re
from collections.abc import AsyncIterator, Callable

from lingo import Engine

from .. import engine
from ..bundle import KEPT_KINDS
from ..scenario import Scenario

log = logging.getLogger(__name__)

#: The kinds after which a run writes nothing more.
TERMINAL = frozenset({"end", "error"})


def _ledger(turn: int, mutations: int) -> dict:
    return {"kind": "ledger", "turn": turn, "mutations": mutations}


class LedgerFold:
    """`bundle.viewer_records`, one record at a time.

    Mutations are counted, not kept. The count goes out as a `ledger` message
    just before the `state` that closes its turn, where the bundle places it. A
    count still open when the run ends or fails goes out just before the `end` or
    `error`, so the terminal record is always the last message of a stream.
    """

    def __init__(self) -> None:
        self._counts: dict[int, int] = {}

    def feed(self, record: dict) -> list[dict]:
        kind = record["kind"]
        if kind == "mutation":
            self._counts[record["turn"]] = self._counts.get(record["turn"], 0) + 1
            return []
        out: list[dict] = []
        if kind == "state" and record["turn"] - 1 in self._counts:
            out.append(_ledger(record["turn"] - 1, self._counts.pop(record["turn"] - 1)))
        elif kind in TERMINAL:
            out.extend(self.flush())
        if kind in KEPT_KINDS:
            out.append(record)
        return out

    def flush(self) -> list[dict]:
        out = [_ledger(turn, n) for turn, n in sorted(self._counts.items())]
        self._counts.clear()
        return out


@dataclasses.dataclass
class _Run:
    messages: list[dict] = dataclasses.field(default_factory=list)
    fold: LedgerFold = dataclasses.field(default_factory=LedgerFold)
    changed: asyncio.Condition = dataclasses.field(default_factory=asyncio.Condition)
    done: bool = False
    task: asyncio.Task | None = None

    def _append(self, messages: list[dict]) -> None:
        for message in messages:
            self.messages.append({**message, "seq": len(self.messages)})

    async def publish(self, record: dict) -> None:
        """The engine's observer: fold the record in and wake every subscriber."""
        async with self.changed:
            self._append(self.fold.feed(record))
            self.changed.notify_all()

    async def finish(self) -> None:
        async with self.changed:
            self._append(self.fold.flush())
            self.done = True
            self.changed.notify_all()


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "run"


def _with_model(scenario: Scenario, model: str) -> Scenario:
    """The scenario with every actor on `model`. The data is what the transcript
    records, so the run says which model actually played. The narrator follows,
    as in `casus run`, unless the scenario names one of its own."""
    actors = {a: {**spec, "model": model} for a, spec in scenario.data["actors"].items()}
    return dataclasses.replace(scenario, data={**scenario.data, "actors": actors})


def _read_messages(path: pathlib.Path) -> list[dict]:
    """A transcript on disk as the numbered stream a live subscriber would get."""
    fold, out = LedgerFold(), []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                break  # a line another process is still writing
            out.extend(fold.feed(record))
    out.extend(fold.flush())
    return [{**message, "seq": i} for i, message in enumerate(out)]


class RunManager:
    """The runs this server started, and the way to follow any run."""

    def __init__(
        self,
        runs_dir: pathlib.Path,
        engine_factory: Callable[[str], Engine] = engine.engine_for,
    ):
        self.runs_dir = pathlib.Path(runs_dir)
        self.engine_factory = engine_factory
        self._runs: dict[str, _Run] = {}

    async def start(
        self, scenario_dir: pathlib.Path, *, seed: int, turns: int | None, model: str | None
    ) -> str:
        """Start a run in the background and return its id, the transcript's stem.

        Loading validates the scenario (the dry turn runs in a worker thread). A
        scenario that does not load raises `ScenarioError` before anything is
        written.
        """
        scenario = await asyncio.to_thread(Scenario.load, scenario_dir)
        if model:
            scenario = _with_model(scenario, model)
        engines = {a: self.engine_factory(scenario.model(a)) for a in scenario.actors}
        first = next(iter(scenario.actors))
        narrator = self.engine_factory(scenario.narrator_model() or scenario.model(first))
        path = self._reserve(scenario.name, seed)
        run = _Run()
        self._runs[path.stem] = run
        run.task = asyncio.create_task(
            self._play(run, scenario, path, seed, turns, engines, narrator)
        )
        return path.stem

    async def _play(self, run, scenario, path, seed, turns, engines, narrator) -> None:
        try:
            await engine.run_async(
                scenario,
                seed=seed,
                out=path,
                engines=engines,
                narrator_engine=narrator,
                turns=turns,
                observer=run.publish,
            )
        except Exception:
            # The transcript's last record already says why; this is for the console.
            log.exception("run %s stopped", path.stem)
        finally:
            await run.finish()

    def _reserve(self, name: str, seed: int) -> pathlib.Path:
        """`<name>-<seed>.jsonl`, or `-2`, `-3`… when taken, created empty at once
        so a second start in the same moment cannot pick it too."""
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{_slug(name)}-{seed}"
        n = 1
        while True:
            suffix = "" if n == 1 else f"-{n}"
            path = self.runs_dir / f"{stem}{suffix}.jsonl"
            try:
                path.touch(exist_ok=False)
                return path
            except FileExistsError:
                n += 1

    async def subscribe(self, run_id: str, after: int = -1) -> AsyncIterator[dict]:
        """Every message of the run numbered after `after`, in order: what is
        there already, then each new one as it comes. Ends after the run's `end`
        or `error`, or when the run is over. Raises KeyError for an unknown run."""
        run = self._runs.get(run_id)
        if run is None:
            path = self.runs_dir / f"{run_id}.jsonl"
            if not path.is_file():
                raise KeyError(run_id)
            for message in _read_messages(path)[after + 1 :]:
                yield message
            return
        index = after + 1
        while True:
            async with run.changed:
                await run.changed.wait_for(lambda: len(run.messages) > index or run.done)
                batch, over = run.messages[index:], run.done
            # Yield outside the lock: a slow reader must never hold up the run.
            for message in batch:
                yield message
                if message["kind"] in TERMINAL:
                    return
            index += len(batch)
            if over:
                return
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_server.py -q`
Expected: PASS.

- [ ] **Step 5: Break it on purpose**

In `subscribe`, change `index = after + 1` to `index = max(after, 0)`. Run `uv run pytest tests/test_server.py -q -k late_and_reconnecting`. Expected: FAIL (the reconnected subscriber gets its last message twice). Revert.

- [ ] **Step 6: Commit**

```bash
git add src/casus/server/runs.py tests/test_server.py
git commit -m "feat(server): the run manager, live runs any number of browsers can follow"
```

---

### Task 5: Starting and following a run over HTTP

**Files:**
- Modify: `src/casus/server/app.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `RunManager` (Task 4), `sse.event_stream` (Task 3), `scenario_dirs` and `RUN_ID` (slice 1).
- Produces: `create_app(*, scenarios_dir, runs_dir, settings=None, run_manager: RunManager | None = None) -> FastAPI`; `POST /api/runs` with body `{scenario, seed, turns, model}` returning `{id}` (404 for an unknown scenario, 422 for a bad seed or turn count, 422 with the findings for a scenario that does not validate); `GET /api/runs/{id}/events` as `text/event-stream`, honouring `Last-Event-ID`, 404 for an unknown or unsafe id. `scenario` is the scenario's directory name, the `dir` of its card.

- [ ] **Step 1: Write the failing tests**

Add `import json` and `import shutil` to the imports of `tests/test_server.py`. Append:

```python
# --- live runs over HTTP --------------------------------------------------------


@pytest.fixture
def live_client(runs):
    manager = RunManager(runs, engine_factory=_live())
    app = create_app(scenarios_dir=SCENARIOS, runs_dir=runs, run_manager=manager)
    with TestClient(app) as client:  # one event loop for the whole test, so runs keep going
        yield client


def _stream(client, run_id: str, headers: dict | None = None) -> str:
    url = f"/api/runs/{run_id}/events"
    with client.stream("GET", url, headers=headers or {}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return "".join(response.iter_text())


def _messages(body: str) -> list[dict]:
    out = []
    for frame in body.split("\n\n"):
        lines = frame.splitlines()
        if not lines or lines[0].startswith(":") or "event: close" in lines:
            continue
        data = next(line for line in lines if line.startswith("data: "))
        out.append(json.loads(data.removeprefix("data: ")))
    return out


def test_posting_a_run_starts_it_and_its_stream_is_its_viewer_records(live_client, runs):
    response = live_client.post("/api/runs", json={"scenario": "smoke", "seed": 9, "turns": 2})
    assert response.status_code == 200
    run_id = response.json()["id"]
    assert run_id == "smoke-9"
    body = _stream(live_client, run_id)
    assert body.endswith(sse.CLOSE.decode())
    messages = _messages(body)
    expected = bundle.viewer_records(engine.read_records(runs / "smoke-9.jsonl"))
    assert _plain(messages) == expected
    assert [m["seq"] for m in messages] == list(range(len(expected)))


def test_a_run_on_a_seed_already_used_gets_its_own_file(live_client, runs):
    before = (runs / "smoke-5.jsonl").read_bytes()
    response = live_client.post("/api/runs", json={"scenario": "smoke", "seed": 5, "turns": 1})
    assert response.json()["id"] == "smoke-5-2"
    _stream(live_client, "smoke-5-2")
    assert (runs / "smoke-5.jsonl").read_bytes() == before


def test_a_recorded_run_streams_from_its_file(live_client, runs):
    messages = _messages(_stream(live_client, "smoke-5"))
    expected = bundle.viewer_records(engine.read_records(runs / "smoke-5.jsonl"))
    assert _plain(messages) == expected


def test_last_event_id_resumes_after_that_message(live_client):
    full = _messages(_stream(live_client, "smoke-5"))
    resumed = _messages(_stream(live_client, "smoke-5", {"Last-Event-ID": "4"}))
    assert resumed == full[5:]


def test_an_unknown_scenario_is_a_404(live_client):
    response = live_client.post("/api/runs", json={"scenario": "atlantis", "seed": 1})
    assert response.status_code == 404


@pytest.mark.parametrize(
    "field, bad", [("seed", "abc"), ("seed", -1), ("seed", 1.5), ("turns", 0)]
)
def test_a_bad_seed_or_turn_count_is_a_422(live_client, runs, field, bad):
    before = sorted(runs.iterdir())
    body = {"scenario": "smoke", "seed": 1, field: bad}
    assert live_client.post("/api/runs", json=body).status_code == 422
    assert sorted(runs.iterdir()) == before


def test_an_invalid_scenario_is_refused_with_its_findings(tmp_path):
    scenarios, runs = tmp_path / "scenarios", tmp_path / "runs"
    shutil.copytree(SMOKE, scenarios / "broken")
    with (scenarios / "broken" / "rules.py").open("a") as fh:
        fh.write("\nimport os\n")
    runs.mkdir()
    manager = RunManager(runs, engine_factory=_live())
    app = create_app(scenarios_dir=scenarios, runs_dir=runs, run_manager=manager)
    with TestClient(app) as client:
        response = client.post("/api/runs", json={"scenario": "broken", "seed": 1})
    assert response.status_code == 422
    assert "forbidden-import" in response.json()["detail"]
    assert list(runs.iterdir()) == []


@pytest.mark.parametrize("bad", ["nope", "..%2Fsmoke-5", ".hidden"])
def test_an_unknown_run_has_no_event_stream(live_client, bad):
    assert live_client.get(f"/api/runs/{bad}/events").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_server.py -q -k "posting or seed or recorded_run_streams or last_event or unknown_scenario or invalid_scenario or event_stream"`
Expected: FAIL with `TypeError: create_app() got an unexpected keyword argument 'run_manager'`.

- [ ] **Step 3: Implement**

In `src/casus/server/app.py`, extend the imports:

```python
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import bundle, engine, studies
from ..scenario import Scenario, ScenarioError
from . import sse
from .runs import RunManager
```

Add after `_card`:

```python
class RunRequest(BaseModel):
    """What the setup form sends. A bad seed or turn count is a 422 from here."""

    scenario: str
    seed: int = Field(default=1, ge=0)
    turns: int | None = Field(default=None, ge=1)
    model: str | None = None


def _run_path(runs_dir: pathlib.Path, run_id: str) -> pathlib.Path:
    """The transcript of `run_id`, or a 404. An id with path characters is a 404
    too, never a read outside `runs/`."""
    path = runs_dir / f"{run_id}.jsonl"
    inside = path.resolve().parent == runs_dir.resolve()
    if not RUN_ID.match(run_id) or not inside or not path.is_file():
        raise HTTPException(404, "no such run")
    return path
```

Change the signature of `create_app` and create the manager right after the static mount:

```python
def create_app(
    *,
    scenarios_dir: pathlib.Path,
    runs_dir: pathlib.Path,
    settings=None,
    run_manager: RunManager | None = None,
) -> FastAPI:
    app = FastAPI(title="casus", docs_url=None, redoc_url=None)
    app.mount("/ui", StaticFiles(directory=UI), name="ui")
    manager = run_manager or RunManager(runs_dir)
```

Replace the body of the slice 1 `run` endpoint so both run endpoints share the path check:

```python
    @app.get("/api/runs/{run_id}")
    def run(run_id: str) -> list[dict]:
        return bundle.viewer_records(engine.read_records(_run_path(runs_dir, run_id)))
```

Add, before `return app`:

```python
    @app.post("/api/runs")
    async def start_run(body: RunRequest) -> dict:
        directory = {d.name: d for d in scenario_dirs(scenarios_dir)}.get(body.scenario)
        if directory is None:
            raise HTTPException(404, "no such scenario")
        model = (body.model or "").strip() or None
        try:
            run_id = await manager.start(
                directory, seed=body.seed, turns=body.turns, model=model
            )
        except ScenarioError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": run_id}

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str, last_event_id: str | None = Header(default=None)):
        _run_path(runs_dir, run_id)
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else -1
        return sse.event_stream(manager.subscribe(run_id, after=after))
```

The run's file exists from the moment `start` returns (it is reserved empty), so `_run_path` accepts a live run's id at once.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_server.py tests/test_cli.py -q`
Expected: PASS, including slice 1's `test_a_run_id_cannot_leave_the_runs_directory`.

- [ ] **Step 5: Commit**

```bash
git add src/casus/server/app.py tests/test_server.py
git commit -m "feat(server): POST /api/runs and the run's event stream"
```

---

### Task 6: A message sent again counts once (`records.js`)

**Files:**
- Modify: `ui/js/records.js` (`RunModel` constructor and `push`)
- Modify: `tests/js/harness.js` (report action counts)
- Test: `tests/test_ui_scripts.py`

**Interfaces:**
- Produces: `RunModel.seq` (the last numbered message pushed, `-1` at first). `RunModel.push(r)` drops `r` when `r.seq` is a number no greater than `run.seq`. Records without `seq` (bundles, `/api/runs/{id}`) are never dropped.

- [ ] **Step 1: Write the failing test**

In `tests/js/harness.js`, add one field to the `out` object, after `mutations`:

```js
  actions: run.playable().map((t) => t.actions.length),
```

Append to `tests/test_ui_scripts.py`:

```python
def test_a_message_sent_again_after_a_reconnect_counts_once(tmp_path):
    """A page that reopens a live stream gets it again from the start. The
    number on each message is what keeps a turn from counting its actions twice."""
    records = [{**r, "seq": i} for i, r in enumerate(_records(tmp_path))]
    cut = next(i for i, r in enumerate(records) if r["kind"] == "action") + 1
    once = _model(records)
    again = _model(records[:cut] + records)
    assert again == once
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ui_scripts.py -q -k counts_once`
Expected: FAIL; `again["actions"]` has turn 1's first action counted twice.

- [ ] **Step 3: Implement**

In `ui/js/records.js`, replace the constructor:

```js
    constructor() {
      this.header = null; this.scenario = {}; this.turns = []; this.deltas = {};
      this.error = null; this.ended = false; this._fns = [];
      this.seq = -1;   // the last numbered message pushed; see push
    }
```

and insert at the top of `push(r)`, before `switch (r.kind)`:

```js
      // A live stream numbers its messages (`seq`), and a page that reopens it
      // is sent them again from the start. A number already seen is dropped, so
      // no turn counts an action twice. Recorded runs carry no numbers.
      if (typeof r.seq === "number") {
        if (r.seq <= this.seq) return;
        this.seq = r.seq;
      }
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ui_scripts.py -q`
Expected: PASS, the slice 1 tests and the new one.

- [ ] **Step 5: Commit**

```bash
git add ui/js/records.js tests/js/harness.js tests/test_ui_scripts.py
git commit -m "feat(ui): a run model drops a live message it has already seen"
```

---

### Task 7: Run from a scenario card (`shell.js`, `i18n.js`, `viewer.follow`)

**Files:**
- Modify: `ui/js/i18n.js` (form strings, `en` and `es`)
- Modify: `ui/js/viewer.js` (add `follow` and `streams`)
- Modify: `ui/js/shell.js` (the Run button and the `run` route)
- Test: `tests/browser/test_viewer.py`

**Interfaces:**
- Consumes: `POST /api/runs`, `GET /api/runs/{id}/events` (Task 5), `RunModel.push` (Task 6), `Casus.shell.onHome`, `Casus.shell.route`, `Casus.shell.json` (slice 1), `serve(runs_dir, **app_kwargs)` from `tests/browser/browser_support.py` (slice 1).
- Produces: `Casus.viewer.follow(url, run) -> {close(), reconnect()}`, which feeds `run` from an `EventSource`, closes on the stream's `end` or `error` record or its `close` event, and reopens from the start after the server refused or closed it; `Casus.viewer.streams`, the `Set` of open follows. The `#/run/<scenario>` route: the setup form (`#setupform` with `#fseed`, `#fturns`, `#fmodel`, `#bstart`), then `Casus.viewer.mount(view, run, {mode: "live"})` once the `scenario` record arrives. Each home scenario card's `[data-actions="scenario"]` row gains a `[data-run]` button.

- [ ] **Step 1: Write the failing browser tests**

In `tests/browser/test_viewer.py`, replace the line `from browser_support import run_records, step_to` with:

```python
import json
import pathlib
import time

import pytest
from browser_support import ROOT, beat, run_records, serve, step_to

from casus.scenario import Scenario
from casus.server.runs import RunManager
from helpers import RAIDING, LiveEngine
```

Append:

```python
# --- live runs (slice 3) --------------------------------------------------------

SMOKE = Scenario.load(ROOT / "scenarios" / "smoke", validate=False)


@pytest.fixture
def live_app(tmp_path):
    """Start the real app over an empty runs directory, with players and a
    narrator that take `delay` seconds per answer. Returns (url, runs_dir).
    Request it before `page`, so the page closes before the server stops."""
    stops = []

    def start(delay: float, reply=None):
        runs = tmp_path / "live-runs"
        runs.mkdir()
        manager = RunManager(
            runs, engine_factory=lambda model: LiveEngine(reply, delay=delay)
        )
        url, stop = serve(runs, run_manager=manager)
        stops.append(stop)
        return url, runs

    yield start
    for stop in stops:
        stop()


def _kinds(path: pathlib.Path) -> list[str]:
    """The record kinds of a transcript being written, up to its last whole line."""
    kinds = []
    for line in path.read_text().splitlines() if path.is_file() else ():
        try:
            kinds.append(json.loads(line)["kind"])
        except json.JSONDecodeError:
            break
    return kinds


def _wait_for(condition, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the run")
        time.sleep(0.05)


def _start(page, url: str, seed: int, turns: int) -> None:
    page.goto(url)
    page.locator('[data-scenario="smoke"] [data-run]').click()
    page.wait_for_selector("#setupform")
    page.fill("#fseed", str(seed))
    page.fill("#fturns", str(turns))
    page.click("#bstart")
    page.wait_for_selector(".visor .livetag")


def _finish(page, path: pathlib.Path) -> None:
    """Wait until the run has written its end and the page has closed its stream."""
    _wait_for(lambda: _kinds(path)[-1:] == ["end"])
    page.wait_for_function("Casus.viewer.streams.size === 0")


def test_live_run_button_opens_the_setup_form(live_app, page):
    url, _ = live_app(delay=0.2)
    page.goto(url)
    page.locator('[data-scenario="smoke"] [data-run]').click()
    page.wait_for_selector("#setupform")
    assert page.url.endswith("#/run/smoke")
    assert page.locator("#fturns").input_value() == str(SMOKE.turns)


def test_live_start_opens_the_viewer_and_writes_a_new_transcript(live_app, page):
    url, runs = live_app(delay=0.2)
    _start(page, url, seed=7, turns=1)
    assert "smoke" in page.locator(".scn").inner_text()
    _finish(page, runs / "smoke-7.jsonl")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/browser/test_viewer.py -q -k live`
Expected: FAIL with a Playwright `TimeoutError` waiting for `[data-scenario="smoke"] [data-run]`.

- [ ] **Step 3: Add the form strings to `ui/js/i18n.js`**

In the `en` table, after the line that ends with `arrived: "arrived from", left: "left",`, add:

```js
      run: "Run", new_run: "New run", scenario: "Scenario", seed: "Seed", turns: "Turns",
      default_model: "Default model", scenario_models: "the scenario's own",
      joins_study: "Joins the study", runs_count: "runs", start: "Start", cancel: "Cancel",
```

In the `es` table, after the line that ends with `arrived: "llega de", left: "se fue",`, add:

```js
      run: "Correr", new_run: "Nueva corrida", scenario: "Escenario", seed: "Semilla",
      turns: "Turnos", default_model: "Modelo por defecto", scenario_models: "los del escenario",
      joins_study: "Guardar en estudio", runs_count: "corridas", start: "Empezar", cancel: "Cancelar",
```

- [ ] **Step 4: Add `follow` to `ui/js/viewer.js`**

Insert before the line `C.viewer = { mount, rationaleFor, BEATS };`:

```js
  // Live: feed a RunModel from a run's event stream. After a network error the
  // browser reconnects on its own and sends the last `seq` it saw as
  // Last-Event-ID, and the server resumes after it. When the server refused or
  // closed the stream, it is reopened from the start and RunModel.push drops
  // what it already has. The run's `end` or `error`, or the server's `close`
  // event, closes it for good. `streams` holds the open ones.
  const streams = new Set();
  function follow(url, run) {
    let source = null, closed = false, tries = 0;
    const handle = {
      close() { closed = true; streams.delete(handle); if (source) source.close(); },
      reconnect() { if (source) source.close(); open(); },
    };
    function open() {
      source = new EventSource(url);
      source.onmessage = (e) => {
        tries = 0;
        const m = JSON.parse(e.data);
        run.push(m);
        if (m.kind === "end" || m.kind === "error") handle.close();
      };
      source.addEventListener("close", () => handle.close());
      source.onerror = () => {
        if (closed || source.readyState !== EventSource.CLOSED) return;
        tries = Math.min(tries + 1, 6);
        setTimeout(() => { if (!closed) open(); }, 500 * tries);
      };
    }
    streams.add(handle);
    open();
    return handle;
  }
```

and replace the export line with:

```js
  C.viewer = { mount, rationaleFor, BEATS, follow, streams };
```

- [ ] **Step 5: Add the Run button and the route to `ui/js/shell.js`**

Insert before the line `C.shell = { start, route, onHome, json };` (after `onHome` and `hooks` are defined):

```js
  // ---- live runs ----
  // A Run button on each scenario card, and #/run/<scenario>: the setup form,
  // then the viewer in live mode, fed by the run's event stream. The viewer is
  // mounted on the stream's first message, the scenario record, because it
  // reads the actors and the language when it mounts.
  onHome((root) => {
    root.querySelectorAll('[data-actions="scenario"]').forEach((row) => {
      const dir = row.closest("[data-scenario]").dataset.scenario;
      const b = document.createElement("button");
      b.className = "btn small primary";
      b.dataset.run = dir;
      b.textContent = "▶ " + C.i18n.t("run");
      b.onclick = () => { location.hash = "#/run/" + encodeURIComponent(dir); };
      row.appendChild(b);
    });
  });

  async function errorText(r) {
    const body = await r.json().catch(() => ({}));
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || r.status);
  }

  route("run", async (root, dir) => {
    const t = C.i18n.t;
    const [scenarios, runs] = await Promise.all([json("/api/scenarios"), json("/api/runs")]);
    const s = scenarios.find((x) => x.dir === dir);
    if (!s) { location.hash = "#/"; return null; }
    const before = runs.filter((r) => r.scenario === s.name).length;
    let source = null, viewer = null;
    root.innerHTML = `
      <div class="setup"><form class="box" id="setupform">
        <h2>${t("new_run")}</h2>
        <div class="field"><label>${t("scenario")}</label><div>${esc(s.name)} <span class="badge ${s.valid ? "ok" : "bad"}">${s.valid ? "✓" : "✗"}</span></div></div>
        <div class="field"><label for="fseed">${t("seed")}</label><input class="inp" id="fseed" name="seed" type="number" min="0" step="1" value="1" required></div>
        <div class="field"><label for="fturns">${t("turns")}</label><input class="inp" id="fturns" name="turns" type="number" min="1" step="1" value="${Number(s.turns) || 1}" required></div>
        <div class="field"><label for="fmodel">${t("default_model")}</label><input class="inp" id="fmodel" name="model" placeholder="${esc(t("scenario_models"))}"></div>
        <div class="field"><label>${t("joins_study")}</label><div>${esc(s.name)} (${before} → ${before + 1} ${t("runs_count")})</div></div>
        ${s.valid ? "" : `<div class="hint">${s.findings.map(esc).join("<br>")}</div>`}
        <div class="hint" id="setuperr"></div>
        <div class="acts"><button class="btn primary" id="bstart" type="submit"${s.valid ? "" : " disabled"}>▶ ${t("start")}</button><button class="btn" type="button" id="bcancel">${t("cancel")}</button></div>
      </form></div>`;
    root.querySelector("#bcancel").onclick = () => { location.hash = "#/"; };
    const form = root.querySelector("#setupform");
    form.onsubmit = async (e) => {
      e.preventDefault();
      const button = form.querySelector("#bstart");
      button.disabled = true;
      const body = {
        scenario: dir, seed: parseInt(form.seed.value, 10), turns: parseInt(form.turns.value, 10),
        model: form.model.value.trim() || null,
      };
      const r = await fetch("/api/runs", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (!r.ok) { root.querySelector("#setuperr").textContent = await errorText(r); button.disabled = false; return; }
      const { id } = await r.json();
      document.getElementById("crumbs").textContent = `› run · ${id}`;
      const run = new C.records.RunModel();
      run.onChange((kind) => {
        if (kind !== "scenario" || viewer) return;
        root.innerHTML = "";
        viewer = C.viewer.mount(root, run, { mode: "live" });
      });
      source = C.viewer.follow("/api/runs/" + encodeURIComponent(id) + "/events", run);
    };
    return () => { if (source) source.close(); if (viewer) viewer.destroy(); };
  });
```

The `.setup`, `.box`, `.field`, `.inp`, `.hint` and `.btn` rules already came into `ui/css/app.css` with the mockup's style block in slice 1; `#view` is `position: relative`, so the overlay fills it.

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/browser/test_viewer.py tests/test_ui_scripts.py -q`
Expected: PASS: the slice 1 viewer tests, the two new live tests, and `test_every_ui_script_parses` for the three changed scripts.

- [ ] **Step 7: Commit**

```bash
git add ui/js/i18n.js ui/js/viewer.js ui/js/shell.js tests/browser/test_viewer.py
git commit -m "feat(ui): run a scenario from its card and follow the run live"
```

---

### Task 8: Live pacing in the viewer

**Files:**
- Modify: `ui/js/viewer.js` (inside `mount`: `unfinished`, `refreshPanes`, the two incomplete banners, `next`, `onChange`)
- Test: `tests/browser/test_viewer.py`

**Interfaces:**
- Consumes: `RunModel.onChange(fn(kind, run, record))` (slice 1), `follow` (Task 7).
- Produces: in live mode, a pane takes its model and its declaration when they arrive, and reads *thinking* until then; beat 1 does not advance to beat 2 until the turn's closing state is in (or the run failed); a turn still being played shows no "did not finish" banner; an `error` record shows at once; the finale follows the last turn once the run ended or failed.

- [ ] **Step 1: Write the failing browser tests**

Append to `tests/browser/test_viewer.py`:

```python
def test_live_beat_one_reads_thinking_until_the_declarations_arrive(live_app, page):
    url, runs = live_app(delay=6.0)
    path = runs / "smoke-2.jsonl"
    _start(page, url, seed=2, turns=1)
    page.wait_for_timeout(3300)  # past every pane's staggered start
    statuses = page.locator(".pane .status").all_inner_texts()
    assert "declaration" not in _kinds(path)  # the premise: nobody has answered yet
    assert len(statuses) == len(SMOKE.actors)
    assert all(s.startswith("thinking") for s in statuses)
    page.wait_for_function(
        f"document.querySelectorAll('.pane .status.done').length === {len(SMOKE.actors)}",
        timeout=15000,
    )
    _finish(page, path)


def test_live_run_plays_to_the_end_without_an_unfinished_banner(live_app, page):
    url, runs = live_app(delay=0.3, reply=RAIDING)
    _start(page, url, seed=5, turns=2)
    page.wait_for_selector(".pane")
    assert page.locator(".banner").count() == 0  # still being played is not unfinished
    _finish(page, runs / "smoke-5.jsonl")
    step_to(page, 2, "dispatch")
    page.keyboard.press("ArrowRight")
    page.wait_for_selector(".finale")
    page.goto(url)
    assert "complete" in page.locator(".runrow", has_text="smoke-5").inner_text()


def test_live_command_post_waits_for_the_turn_to_resolve(live_app, page):
    """The narrator writes after the rules resolve and before the state that
    closes the turn. A presenter who presses on must not reach the command post
    before that state, or it would draw a turn with no outcome."""
    url, runs = live_app(delay=2.5, reply=RAIDING)
    path = runs / "smoke-3.jsonl"
    _start(page, url, seed=3, turns=1)
    page.click("#bplay")  # auto off: the test paces the room
    page.wait_for_function(
        f"document.querySelectorAll('.pane .status.done').length === {len(SMOKE.actors)}"
    )
    page.keyboard.press("ArrowRight")
    assert beat(page) == "declaring"
    assert _kinds(path).count("state") == 1  # the narrator is still writing
    page.keyboard.press("ArrowRight")
    assert beat(page) == "declaring"
    _finish(page, path)
    page.keyboard.press("ArrowRight")
    assert beat(page) == "resolving"
    assert page.locator(".banner").count() == 0
    mutations = _kinds(path).count("mutation")
    assert page.locator("#vready").inner_text().startswith(str(mutations))


def test_live_reconnect_counts_nothing_twice(live_app, page):
    """Review Focus 2 in a real browser: the page reopens its stream mid-run,
    the server sends everything again, and turn 1 still shows each action once."""
    url, runs = live_app(delay=0.5, reply=RAIDING)
    path = runs / "smoke-6.jsonl"
    _start(page, url, seed=6, turns=2)
    _wait_for(lambda: _kinds(path).count("state") >= 2)  # turn 1 is in
    page.evaluate("Casus.viewer.streams.forEach((s) => s.reconnect())")
    _finish(page, path)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    page.click("#bplay")  # auto off
    page.locator('#vdots .dot[data-i="0"]').click()
    step_to(page, 1, "declaring")
    actions = sum(1 for r in records if r["kind"] == "action" and r["turn"] == 1)
    assert page.locator(".pane .chip").count() == actions
    step_to(page, 1, "resolving")
    mutations = sum(1 for r in records if r["kind"] == "mutation" and r["turn"] == 1)
    assert page.locator("#vready").inner_text().startswith(str(mutations))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/browser/test_viewer.py -q -k "thinking_until or plays_to_the_end or command_post_waits"`
Expected: FAIL. The panes never take their declarations, so `.status.done` never appears; a live turn in beat 1 shows "This turn did not finish."; the second arrow press reaches `resolving` before the state is in.

- [ ] **Step 3: Implement**

All changes are inside `mount` in `ui/js/viewer.js`.

After the line `const T = () => turns()[V.ti];`, add:

```js
    // Recorded, a turn without its closing state did not finish. Live, it may
    // still be resolving, unless the run is over.
    const unfinished = (cur) => !cur.complete && (!live || run.ended || !!run.error);
```

In `warRoom()` and in `commandPost()`, replace

```js
          ${cur.complete ? "" : `<div class="banner">${t("incomplete")}</div>`}
```

with

```js
          ${unfinished(cur) ? `<div class="banner">${t("incomplete")}</div>` : ""}
```

After the `paneFrame` function, add:

```js
    // Live, prompts and declarations reach a war room already on screen.
    function refreshPanes() {
      const cur = T(), declared = C.records.declarations(cur);
      for (const p of V.panes) {
        const prompt = cur.prompts.find((x) => x.actor === p.id);
        p.model = prompt ? prompt.model : "";
        p.d = declared.find((x) => x.actor === p.id) || null;
        const el = document.getElementById("pane-" + p.id);
        if (!el) continue;
        el.querySelector(".model").textContent = p.model;
        el.querySelector(".assess em").textContent = p.d ? p.d.assessment : "";
      }
    }
```

Replace `next()` with:

```js
    function next() {
      if (V.done || !T()) return;
      if (V.beat === 0) { if (!paneFrame() && !live) { V.clock = 1e9; paneFrame(); return; } enter(1); }
      else if (V.beat === 1 && live && !T().complete && !run.error) return;   // not resolved yet
      else if (V.beat < 3) enter(V.beat + 1);
      else if (V.ti < turns().length - 1) { V.ti++; enter(0); }
      else if (!live || run.ended || run.error) { V.done = true; finale(); }
    }
```

Replace the two lines

```js
    // A live run may start with no playable turn; enter the first when it appears.
    const onChange = () => { if (V.beat === 0 && !V.panes.length && T()) enter(0); else header(); };
```

with:

```js
    // Live, records keep arriving after mount: enter the first turn when it
    // appears, give each pane its model and its declaration as they land, and
    // show a failure as soon as it is recorded.
    const onChange = (kind, _run, r) => {
      if (V.beat === 0 && !V.panes.length && T()) { enter(0); return; }
      const cur = T();
      if ((kind === "prompt" || kind === "action") && cur && r.turn === cur.turn && V.beat <= 1) {
        refreshPanes();
        if (V.beat === 1) reveal();
      }
      if (kind === "error" && live) {
        $("#stage").insertAdjacentHTML("beforeend", `<div class="banner">${t("failed")} ${esc(r.error)}</div>`);
      }
      header();
    };
```

Why beat 1 *thinking* needs nothing more: `paneFrame` already reads *thinking* while `p.d` is null, and once `refreshPanes` sets it the elapsed clock is past the pane's typing, so the rationale appears whole. That is the spec's behaviour for an endpoint that does not stream; slice 4 makes it type.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/browser/test_viewer.py -q`
Expected: PASS: every slice 1 viewer test (recorded mode is untouched: `unfinished` is `!complete` there, and `onChange` never fires after a recorded mount) and the six live tests.

- [ ] **Step 5: Break it on purpose**

In `ui/js/records.js`, delete the line `if (r.seq <= this.seq) return;`. Run `uv run pytest tests/browser/test_viewer.py -q -k reconnect`. Expected: FAIL (turn 1 shows its chips twice). Restore the line.

- [ ] **Step 6: Commit**

```bash
git add ui/js/viewer.js tests/browser/test_viewer.py
git commit -m "feat(ui): live pacing, panes that wait for their declarations"
```

---

### Task 9: Docs, and the acceptance check

**Files:**
- Modify: `README.md` ("Install and run", the module table), `docs/specs/2026-09-28-interface-design.md` (status header), `docs/plans/2026-09-29-casus-app-plan.md` (slice table: the PR number only)

- [ ] **Step 1: README**

After the `uv run casus serve` line that slice 1 added to "Install and run", add this paragraph below the code block:

```markdown
A live run starts from the app. **Run** on a scenario card asks for a seed, a
number of turns and, if you want one, a model for every actor, then plays the
run in the viewer while it happens. The transcript goes to
`runs/<scenario>-<seed>.jsonl`, or `-2`, `-3` and so on when that name is taken,
and it is the same file `casus run` writes, so `casus verify` and `casus bundle`
work on it. The endpoint comes from the same `BASE_URL` and `API_KEY` as the
command line. A browser that opens a run late, or loses its connection, catches
up from the start and counts nothing twice.
```

In the module table, change the `server/` row's description to: "The local app: the shell, the scenario and run endpoints, and live runs followed over server-sent events".

- [ ] **Step 2: Spec status**

In the frontmatter of `docs/specs/2026-09-28-interface-design.md`, change the `status` line from slice 1's `"slice 1 implemented (PR #<n>); slices 3-5 pending"` to `"slices 1 and 3 implemented (PRs #<n>, #<this PR>); slices 4-5 pending"`, keeping slice 1's number. In the master plan's slice table, add this PR's number to row 3; change nothing else there.

- [ ] **Step 3: The full suite**

Run: `make test`
Expected: PASS. Run `make lint` as well and fix anything it reports in the files this slice touched.

- [ ] **Step 4: Acceptance, the way a person does it**

```bash
export BASE_URL=https://openrouter.ai/api/v1
export API_KEY=$(cat ~/.config/openrouter.token)
uv run casus serve
```

In the browser that opens:

1. Click **▶ Run** on the smoke card. The form shows seed 1, turns 3 and the study line. Set turns to 2 and press **Start**.
2. Watch day 1: the panes read *thinking* until the models answer, then each rationale appears whole; the room moves on by itself to declaring, resolving (with the mutation count) and the dispatch, then day 2, then **END**.
3. Start a second run with the same seed. It must be written as `runs/smoke-1-2.jsonl`, and `runs/smoke-1.jsonl` must be untouched.
4. During the second run, open DevTools, set the Network tab to *Offline* for about five seconds, then back to *No throttling*. The run continues. At the end, click the first day marker, press → to the declarations, and check each actor's actions appear once.
5. Start a run on `reference` with turns 1, so the narrator it names writes the dispatch.
6. Go home: the three runs are listed as complete. Open one with **View**; it plays as a recorded run.
7. In a terminal: `uv run casus verify runs/smoke-1.jsonl` must print `replay OK`.

Note in the PR body what was checked, on which endpoint and model, and anything that looked wrong.

- [ ] **Step 5: Commit and open the PR**

```bash
git add README.md docs/specs/2026-09-28-interface-design.md docs/plans/2026-09-29-casus-app-plan.md
git commit -m "docs: live runs from the app, and how to check them"
git push -u origin 5-slice-3-live-runs
gh pr create --title "feat: live runs from the app" --body "Part of #5. ..."
```

---

## Contract changes needed

> Applied during plan review (2026-09-29) to the master plan's "Amendments from the slice plans" section, resolved against the other slices. Do not edit the master plan again for these; if the code must differ from the amendments, change the amendments in this slice's PR.

These change or add to what the master plan names. Each must land in `docs/plans/2026-09-29-casus-app-plan.md` in this slice's PR.

1. **`create_app` gains a keyword.** `def create_app(*, scenarios_dir, runs_dir, settings=None, run_manager: RunManager | None = None) -> FastAPI`. Tests and `browser_support.serve(runs_dir, run_manager=...)` inject a manager whose engine factory makes `LiveEngine`s; `casus serve` passes nothing and gets `RunManager(runs_dir)` with the real `engine_for`.
2. **`RunManager.subscribe` gains `after`.** `def subscribe(self, run_id: str, after: int = -1) -> AsyncIterator[dict]`: the messages numbered after `after`. Every message carries `"seq": int`, numbered from 0 per run. It raises `KeyError` for an unknown run. `engine_factory` is `Callable[[str], Engine]`, called with a model name, once per actor and once for the narrator.
3. **The event stream's wire format.** `GET /runs/{id}/events` sends each message as `id: <seq>` plus `data: <json>`, sends `: keepalive` comments after 15 s of silence, ends with an `event: close` frame, and honours `Last-Event-ID`. Its messages are `bundle.viewer_records` of the transcript (with `ledger`, without `mutation` or `declaration`), plus `seq`. Slice 4's `delta` messages go into the same numbered list for runs in memory.
4. **`POST /runs` semantics.** `scenario` is the card's `dir`; `seed` ≥ 0 (default 1), `turns` ≥ 1 or null; `model`, when given, replaces every actor's model in the data the transcript records, and the narrator follows unless the scenario names its own. 404 for an unknown scenario, 422 for a bad body or a scenario that does not validate.
5. **Engine behaviour.** `run_async` writes an `error` record for any exception that stops a run, not only `RuleFailed`, on the turn being played; the text is `"<TypeName>: <message>"` for non-rule failures. `engine.Observer` is exported.
6. **JavaScript interfaces.** `RunModel.seq` (the last numbered message pushed, `-1` at first), and `push` drops a message whose `seq` is not above it. `Casus.viewer.follow(url, run) -> {close(), reconnect()}` and `Casus.viewer.streams` (a `Set` of open follows).
7. **File structure table.** `engine.py`: "3: run_async(observer=...), an error record for any failure". `js/records.js`: add "3: drops a re-sent message by seq". `js/i18n.js`: add "3: the run form's strings". `js/shell.js`: add "3: the Run button and `#/run/<scenario>`". `js/viewer.js`: "3: follow(), live pacing". Tests: `tests/test_ui_scripts.py` and `tests/js/harness.js` add "3"; `tests/test_engine.py` gains slice 3 tests; `tests/helpers.py` (which predates the table) gains `RAIDING`, `Gate` and `LiveEngine`.
