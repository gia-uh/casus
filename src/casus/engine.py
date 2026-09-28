"""The turn loop, the transcript, and replay verification.

The transcript is the product. It carries the scenario, every state, every prompt
sent, every validated declaration received, every action, and every resolution.
Given one, `replay` re-derives the whole run without touching a network and
compares each derived state digest against the recorded one. A mismatch means
non-determinism leaked into the resolver, and it fails loudly rather than
reporting a plausible run.

The loop is async because lingo is. Within a turn the random draws happen first,
in a fixed actor order, and only then do the calls go out together — determinism
and concurrency are separated on purpose, and the transcript is written in actor
order regardless of which reply lands first.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import pathlib
import random
import time
from collections.abc import Iterator

from lingo import LLM, Engine

from . import narrator
from .players import Player, PlayerTurn
from .scenario import Scenario
from .v1 import rules
from .v1.state import Action, Resolution, WorldState

RECORD_KINDS = frozenset(
    {"scenario", "state", "prompt", "declaration", "action", "resolution", "narrative", "end"}
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
        self.records: list[dict] = []
        self._fh = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = path.open("w", encoding="utf-8")

    def write(self, record: dict) -> None:
        assert record["kind"] in RECORD_KINDS, f"unknown record kind {record['kind']!r}"
        record.setdefault("ts", time.time())
        self.records.append(record)
        if self._fh is not None:
            self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def engine_for(model: str, **kwargs) -> Engine:
    """A lingo engine for one model.

    Endpoint and credentials come from lingo's own environment convention
    (`BASE_URL`, `API_KEY`), because transport is lingo's business and casus has
    no opinion about it.
    """
    return Engine(LLM(model=model, **kwargs))


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
        actor_id: Player(
            actor_id=actor_id,
            briefing=scenario.briefing(actor_id),
            model=scenario.model(actor_id),
            engine=engines[actor_id],
            language=scenario.language(),
        )
        for actor_id in scenario.actors
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
            # The whole scenario travels inside the transcript, so a replay needs
            # nothing but this one file.
            "scenario": scenario.raw,
        }
    )
    _write_state(transcript, state)

    try:
        for _ in range(total_turns):
            order = sorted(players)
            # Draws first, in a fixed order: this is where determinism lives.
            views = {a: players[a].view(state, rng) for a in order}
            for actor_id in order:
                transcript.write(
                    {
                        "kind": "prompt",
                        "turn": state.turn,
                        "actor": actor_id,
                        "model": players[actor_id].model,
                        "prompt": views[actor_id][0],
                        "legal": list(views[actor_id][1]),
                    }
                )

            results = await asyncio.gather(
                *(players[a].decide(state, *views[a]) for a in order)
            )
            declared: list[Action] = []
            for actor_id, player_turn in zip(order, results, strict=True):
                declared.extend(player_turn.actions)
                _write_declaration(transcript, state.turn, actor_id, player_turn)

            state, resolutions = rules.resolve(state, declared, rng)
            for resolution in resolutions:
                transcript.write(
                    {
                        "kind": "resolution",
                        "turn": state.turn - 1,
                        "resolution": resolution.to_json(),
                    }
                )
            if narrator_engine is not None:
                text = await narrator.narrate(
                    state, resolutions, narrator_engine, scenario.language()
                )
                transcript.write({"kind": "narrative", "turn": state.turn - 1, "text": text})

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
    """Serves the declarations a run already produced, in recorded order.

    Replay does not call a model. It re-runs the resolver over the same
    declarations and checks the arithmetic still lands in the same place.
    """

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


def replay(path: pathlib.Path | str) -> RunSummary:
    """Re-derive the run from its recorded declarations and verify every state."""
    records = read_records(path)
    header = next((r for r in records if r["kind"] == "scenario"), None)
    if header is None:
        raise ReplayMismatch("transcript has no scenario record")

    scenario = Scenario.from_dict(header["scenario"])
    recorded_states = {r["turn"]: r for r in records if r["kind"] == "state"}

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

    for state in summary.states:
        recorded = recorded_states.get(state.turn)
        if recorded is None:
            raise ReplayMismatch(f"turn {state.turn} has no recorded state to compare against")
        if recorded["digest"] != state.digest():
            raise ReplayMismatch(
                f"turn {state.turn} diverged: "
                f"{_first_difference(recorded['state'], state.to_json())}"
            )
    return summary


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


def resolutions_of(records: list[dict], turn: int) -> list[Resolution]:
    return [
        Resolution.from_json(r["resolution"])
        for r in records
        if r["kind"] == "resolution" and r["turn"] == turn
    ]
