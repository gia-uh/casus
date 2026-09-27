"""The turn loop, the transcript, and replay verification.

The transcript is the product. It carries the scenario, every state, every prompt
sent, every raw completion received, every action declared and every resolution
computed. Given one, `replay` re-derives the whole run without touching a
network, and compares each derived state digest against the recorded one. A
mismatch means some non-determinism leaked into the resolver, and it fails loudly
rather than reporting a plausible run.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import random
import time
from collections.abc import Callable, Iterator

from . import rules
from .llm import LLMResult, complete
from .players import Player, PlayerTurn
from .scenario import Scenario
from .state import Action, Resolution, WorldState

RECORD_KINDS = frozenset(
    {"scenario", "state", "prompt", "response", "action", "resolution", "narrative", "end"}
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
    prompt_tokens: int = 0
    completion_tokens: int = 0
    schema_failures: int = 0

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


def run(
    scenario: Scenario,
    seed: int = 1,
    out: pathlib.Path | str | None = None,
    call: Callable[..., LLMResult] = complete,
    narrate: Callable[..., str] | None = None,
    turns: int | None = None,
) -> RunSummary:
    """Play the scenario and write a transcript."""
    transcript = _Transcript(pathlib.Path(out) if out is not None else None)
    rng = random.Random(seed)
    state = scenario.initial_state()
    total_turns = turns if turns is not None else scenario.turns

    players = {
        actor_id: Player(
            actor_id=actor_id,
            briefing=scenario.briefing(actor_id),
            model=scenario.model(actor_id),
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
            # The whole scenario travels inside the transcript so a replay needs
            # nothing but this one file.
            "scenario": scenario.raw,
        }
    )
    transcript.write(
        {
            "kind": "state",
            "turn": state.turn,
            "digest": state.digest(),
            "state": state.to_json(),
        }
    )

    try:
        for _ in range(total_turns):
            declared: list[Action] = []
            for actor_id in sorted(players):
                recorder = _recording_call(transcript, state.turn, actor_id, call)
                player_turn = players[actor_id].decide(state, rng, call=recorder)
                declared.extend(player_turn.actions)
                summary.prompt_tokens += player_turn.tokens[0]
                summary.completion_tokens += player_turn.tokens[1]
                summary.schema_failures += player_turn.schema_failures
                _write_actions(transcript, state.turn, actor_id, player_turn)

            state, resolutions = rules.resolve(state, declared, rng)
            for resolution in resolutions:
                transcript.write(
                    {
                        "kind": "resolution",
                        "turn": state.turn - 1,
                        "resolution": resolution.to_json(),
                    }
                )
            if narrate is not None:
                text = narrate(state, resolutions)
                transcript.write({"kind": "narrative", "turn": state.turn - 1, "text": text})

            transcript.write(
                {
                    "kind": "state",
                    "turn": state.turn,
                    "digest": state.digest(),
                    "state": state.to_json(),
                }
            )
            summary.states.append(state)
            summary.turns += 1

        transcript.write(
            {
                "kind": "end",
                "turn": state.turn,
                "prompt_tokens": summary.prompt_tokens,
                "completion_tokens": summary.completion_tokens,
                "schema_failures": summary.schema_failures,
            }
        )
    finally:
        transcript.close()
    return summary


def _recording_call(
    transcript: _Transcript, turn: int, actor_id: str, inner: Callable[..., LLMResult]
) -> Callable[..., LLMResult]:
    """Wrap a completion function so the prompt is on disk before the call and
    the raw reply is on disk before anything reads it.

    Recording from the engine rather than from inside `Player` is what makes the
    ordering guarantee true: a player that retries produces two prompt/response
    pairs, both captured, in the order they happened.
    """

    def recorded(model, messages, schema=None, temperature=0.7) -> LLMResult:
        transcript.write(
            {
                "kind": "prompt",
                "turn": turn,
                "actor": actor_id,
                "model": model,
                "messages": messages,
            }
        )
        result = inner(model, messages, schema=schema, temperature=temperature)
        transcript.write(
            {
                "kind": "response",
                "turn": turn,
                "actor": actor_id,
                "model": result.model,
                "text": result.text,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            }
        )
        return result

    return recorded


def _write_actions(
    transcript: _Transcript, turn: int, actor_id: str, player_turn: PlayerTurn
) -> None:
    for action in player_turn.actions:
        transcript.write(
            {
                "kind": "action",
                "turn": turn,
                "actor": actor_id,
                "action": action.to_json(),
                "rationale": player_turn.rationale,
                "assessment": player_turn.assessment,
                "schema_failures": player_turn.schema_failures,
                "prompt": player_turn.prompt,
            }
        )


# --- replay -----------------------------------------------------------------


def read_records(path: pathlib.Path | str) -> list[dict]:
    with pathlib.Path(path).open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def replay(path: pathlib.Path | str) -> RunSummary:
    """Re-derive the run from its recorded completions and verify every state.

    Raises `ReplayMismatch` naming the first turn and field that differs.
    """
    records = read_records(path)
    header = next((r for r in records if r["kind"] == "scenario"), None)
    if header is None:
        raise ReplayMismatch("transcript has no scenario record")

    scenario = Scenario.from_dict(header["scenario"])
    recorded_states = {r["turn"]: r for r in records if r["kind"] == "state"}
    replies = _reply_queue(records)

    def canned(model, messages, schema=None, temperature=0.7) -> LLMResult:
        try:
            return next(replies)
        except StopIteration as exc:
            raise ReplayMismatch(
                "the transcript ran out of recorded replies before the run finished"
            ) from exc

    summary = run(
        scenario,
        seed=int(header["seed"]),
        out=None,
        call=canned,
        turns=int(header["turns"]),
    )

    for state in summary.states:
        recorded = recorded_states.get(state.turn)
        if recorded is None:
            raise ReplayMismatch(f"turn {state.turn} has no recorded state to compare against")
        if recorded["digest"] != state.digest():
            raise ReplayMismatch(
                f"turn {state.turn} diverged: {_first_difference(recorded['state'], state.to_json())}"
            )
    return summary


def _reply_queue(records: list[dict]) -> Iterator[LLMResult]:
    for record in records:
        if record["kind"] != "response":
            continue
        yield LLMResult(
            text=record["text"],
            raw={"replayed": True},
            model=record.get("model", ""),
            prompt_tokens=int(record.get("prompt_tokens", 0)),
            completion_tokens=int(record.get("completion_tokens", 0)),
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


def resolutions_of(records: list[dict], turn: int) -> list[Resolution]:
    return [
        Resolution.from_json(r["resolution"])
        for r in records
        if r["kind"] == "resolution" and r["turn"] == turn
    ]
