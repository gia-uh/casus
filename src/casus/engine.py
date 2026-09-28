"""The turn loop, the transcript, and replay verification.

The transcript is the product. It carries the scenario and its rules, every
state, every prompt sent, every validated declaration received, every action,
every event and every mutation. Given one, `replay` re-derives the whole run
without touching a network and compares each derived state digest against the
recorded one. A mismatch means non-determinism leaked into the rules, and it
fails loudly rather than reporting a plausible run.

The loop is async because lingo is. Within a turn the random draws happen first,
in a fixed actor order, and only then do the calls go out together, and the
transcript is written in actor order regardless of which reply lands first.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import pathlib
import random
import time
from collections.abc import Callable, Iterator

from lingo import LLM, Engine

from . import narrator
from .players import Player, PlayerTurn, believed
from .resolver import RuleFailed, resolve
from .scenario import Scenario
from .state import Action, WorldState

__all__ = ["ReplayMismatch", "RuleFailed", "RunSummary", "replay", "replay_on", "run"]

RECORD_KINDS = frozenset(
    {
        "scenario",
        "state",
        "prompt",
        "declaration",
        "action",
        "event",
        "mutation",
        "narrative",
        "error",
        "end",
    }
)


class ReplayMismatch(AssertionError):
    """A replayed state diverged from the recorded one."""


@dataclasses.dataclass
class RunSummary:
    scenario: str
    seed: int
    turns: int
    states: list[WorldState]
    transcript: pathlib.Path | None = None

    @property
    def final(self) -> WorldState:
        return self.states[-1]


class _Transcript:
    """Append-only JSONL writer. Flushes every record, so a run killed halfway
    still replays up to the last completed turn."""

    def __init__(self, path: pathlib.Path | None):
        self.path = path
        self._fh = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = path.open("w", encoding="utf-8")

    def write(self, record: dict) -> None:
        assert record["kind"] in RECORD_KINDS, f"unknown record kind {record['kind']!r}"
        record.setdefault("ts", time.time())
        if self._fh is not None:
            self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def engine_for(model: str, **kwargs) -> Engine:
    """A lingo engine for one model. Endpoint and credentials come from lingo's
    own environment convention (`BASE_URL`, `API_KEY`)."""
    return Engine(LLM(model=model, **kwargs))


def _resolve(scenario: Scenario, state: WorldState, actions: list[Action], rng: random.Random):
    return resolve(
        state,
        actions,
        scenario.ruleset,
        rng,
        scenario.actions,
        scenario.resource_bounds(),
        scenario.attribute_bounds(),
    )


async def run_async(
    scenario: Scenario,
    seed: int = 1,
    out: pathlib.Path | str | None = None,
    engines: dict[str, Engine] | None = None,
    narrator_engine: Engine | None = None,
    turns: int | None = None,
) -> RunSummary:
    """Play the scenario and write a transcript."""
    transcript = _Transcript(pathlib.Path(out) if out is not None else None)
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
    transcript.write(
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
    _write_state(transcript, state)

    try:
        for _ in range(total_turns):
            order = sorted(players)
            # Draws first, in a fixed order: this is where determinism lives.
            try:
                views = {a: players[a].view(state, rng) for a in order}
            except RuleFailed as exc:
                transcript.write({"kind": "error", "turn": state.turn, "error": str(exc)})
                raise
            for actor_id in order:
                prompt, offered = views[actor_id]
                transcript.write(
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
                _write_declaration(transcript, state.turn, actor_id, player_turn)

            turn = state.turn
            try:
                state, events, mutations = _resolve(scenario, state, declared, rng)
            except RuleFailed as exc:
                transcript.write({"kind": "error", "turn": turn, "error": str(exc)})
                raise
            for event in events:
                transcript.write({"kind": "event", "turn": turn, "event": event.to_json()})
            for mutation in mutations:
                transcript.write({"kind": "mutation", **mutation.to_json()})
            if narrator_engine is not None:
                text = await narrator.narrate(state, events, narrator_engine, scenario)
                transcript.write({"kind": "narrative", "turn": turn, "text": text})

            _write_state(transcript, state)
            summary.states.append(state)
            summary.turns += 1

        transcript.write({"kind": "end", "turn": state.turn})
    finally:
        transcript.close()
    return summary


def run(scenario: Scenario, **kwargs) -> RunSummary:
    """Synchronous entry point. The loop is async because lingo is."""
    return asyncio.run(run_async(scenario, **kwargs))


def _write_state(transcript: _Transcript, state: WorldState) -> None:
    transcript.write(
        {
            "kind": "state",
            "turn": state.turn,
            "digest": state.digest(),
            "state": state.to_json(),
        }
    )


def _write_declaration(
    transcript: _Transcript, turn: int, actor_id: str, player_turn: PlayerTurn
) -> None:
    transcript.write(
        {
            "kind": "declaration",
            "turn": turn,
            "actor": actor_id,
            "model": player_turn.model,
            "declaration": player_turn.declaration,
        }
    )
    for action in player_turn.actions:
        transcript.write(
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


# --- replay -----------------------------------------------------------------


def read_records(path: pathlib.Path | str) -> list[dict]:
    with pathlib.Path(path).open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class _RecordedEngine:
    """Serves the declarations a run already produced, in recorded order."""

    def __init__(self, declarations: Iterator[dict]):
        self._queue = list(declarations)
        self._index = 0

    async def create(self, context, schema, *instructions):
        if self._index >= len(self._queue):
            raise ReplayMismatch(
                "the transcript ran out of recorded declarations before the run finished"
            )
        payload = self._queue[self._index]
        self._index += 1
        return schema.model_validate(payload)


def _header(records: list[dict]) -> dict:
    header = next((r for r in records if r["kind"] == "scenario"), None)
    if header is None:
        raise ReplayMismatch("transcript has no scenario record")
    return header


def replay(path: pathlib.Path | str) -> RunSummary:
    """Re-derive the run from its recorded declarations and verify every state."""
    records = read_records(path)
    header = _header(records)
    scenario = Scenario.from_parts(header["scenario"], header["rules_source"])

    per_actor: dict[str, list[dict]] = {}
    for record in records:
        if record["kind"] == "declaration":
            per_actor.setdefault(record["actor"], []).append(record["declaration"])

    engines = {a: _RecordedEngine(iter(per_actor.get(a, []))) for a in scenario.actors}
    summary = run(
        scenario,
        seed=int(header["seed"]),
        out=None,
        engines=engines,  # type: ignore[arg-type]
        turns=int(header["turns"]),
    )
    _verify(records, summary)
    return summary


def replay_on(
    scenario: Scenario,
    transcript: pathlib.Path | str,
    translate: Callable[[dict], Action | None],
) -> RunSummary:
    """Re-derive a recorded run against a different scenario implementation.

    Reads the recorded actions rather than re-validating declarations, so a run
    recorded under another vocabulary can be replayed: `translate` turns each
    recorded action into this engine's `Action`, or None to drop it. The view
    hook still runs for every actor, in sorted order, so the random draws line up
    with the run that produced the transcript.
    """
    records = read_records(transcript)
    header = _header(records)
    rng = random.Random(int(header["seed"]))
    state = scenario.initial_state()
    summary = RunSummary(
        scenario=scenario.name, seed=int(header["seed"]), turns=0, states=[state]
    )
    for _ in range(int(header["turns"])):
        turn = state.turn
        actions = [
            translate(r["action"])
            for r in records
            if r["kind"] == "action" and r["turn"] == turn
        ]
        for actor in sorted(scenario.actors):
            believed(scenario, state, actor, rng)
        state, _, _ = _resolve(scenario, state, [a for a in actions if a is not None], rng)
        summary.states.append(state)
        summary.turns += 1
    return summary


def _verify(records: list[dict], summary: RunSummary) -> None:
    recorded_states = {r["turn"]: r for r in records if r["kind"] == "state"}
    for state in summary.states:
        recorded = recorded_states.get(state.turn)
        if recorded is None:
            raise ReplayMismatch(f"turn {state.turn} has no recorded state to compare against")
        # Content as well as digest: a hand-edited state whose digest was left
        # alone would otherwise pass.
        if recorded["digest"] != state.digest() or recorded["state"] != state.to_json():
            raise ReplayMismatch(
                f"turn {state.turn} diverged: "
                f"{_first_difference(recorded['state'], state.to_json())}"
            )


def _first_difference(recorded: object, derived: object, path: str = "") -> str:
    """Name the first field that differs, so a mismatch is actionable."""
    if isinstance(recorded, dict) and isinstance(derived, dict):
        for key in sorted(set(recorded) | set(derived)):
            here = f"{path}.{key}" if path else str(key)
            if key not in recorded:
                return f"{here} present only in the replay"
            if key not in derived:
                return f"{here} present only in the recording"
            found = _first_difference(recorded[key], derived[key], here)
            if found:
                return found
        return ""
    if isinstance(recorded, list) and isinstance(derived, list):
        if len(recorded) != len(derived):
            return f"{path} has {len(recorded)} entries recorded and {len(derived)} replayed"
        for index, (a, b) in enumerate(zip(recorded, derived, strict=True)):
            found = _first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
        return ""
    if recorded != derived:
        return f"{path}: recorded {recorded!r}, replayed {derived!r}"
    return ""
