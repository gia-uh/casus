import json
import pathlib

import pytest

from casus import engine
from casus.llm import LLMResult
from casus.scenario import Scenario

SMOKE = pathlib.Path(__file__).parent.parent / "scenarios" / "smoke.yaml"


def _scenario() -> Scenario:
    return Scenario.load(SMOKE)


def _scripted(replies: dict[str, str] | None = None):
    """A completion function that answers from a per-actor script.

    Keyed on the actor's identifier, which it reads out of the prompt, so the
    same script works however many turns the engine plays.
    """
    replies = replies or {}
    default = '{"actions":[{"type":"hold"}],"rationale":"wait","assessment":"they wait too"}'

    def call(model, messages, schema=None, temperature=0.7) -> LLMResult:
        prompt = messages[1]["content"]
        actor = prompt.split("You are ")[1].split("(")[1].split(")")[0]
        return LLMResult(
            text=replies.get(actor, default),
            raw={"scripted": True},
            model=model,
            prompt_tokens=10,
            completion_tokens=5,
        )

    return call


def _records(path) -> list[dict]:
    return engine.read_records(path)


# --- replay fidelity, the claim the whole design rests on -------------------


def test_replay_reproduces_the_state_trajectory_exactly(tmp_path):
    out = tmp_path / "run.jsonl"
    engine.run(_scenario(), seed=42, out=out, call=_scripted(), turns=3)

    recorded = [r for r in _records(out) if r["kind"] == "state"]
    replayed = engine.replay(out).states
    assert len(recorded) == len(replayed) == 4  # initial state plus three turns
    assert [r["digest"] for r in recorded] == [s.digest() for s in replayed]


def test_replay_fails_loudly_when_a_recorded_state_was_tampered_with(tmp_path):
    """Break it on purpose. A verification that cannot fail is worth less than
    none, because it licenses shipping."""
    out = tmp_path / "run.jsonl"
    engine.run(_scenario(), seed=42, out=out, call=_scripted(), turns=3)
    _corrupt_fuel(out, turn=2)

    with pytest.raises(engine.ReplayMismatch) as excinfo:
        engine.replay(out)
    message = str(excinfo.value)
    assert "turn 2" in message
    assert "fuel_days" in message


def test_replay_fails_when_the_transcript_is_truncated(tmp_path):
    out = tmp_path / "run.jsonl"
    engine.run(_scenario(), seed=1, out=out, call=_scripted(), turns=3)
    lines = out.read_text().splitlines()
    out.write_text("\n".join(lines[: len(lines) // 2]) + "\n")

    with pytest.raises(engine.ReplayMismatch):
        engine.replay(out)


def test_replay_needs_nothing_but_the_transcript(tmp_path):
    """The scenario travels inside the file, so a transcript handed to a student
    replays with no other artifact present."""
    out = tmp_path / "run.jsonl"
    engine.run(_scenario(), seed=7, out=out, call=_scripted(), turns=2)
    header = next(r for r in _records(out) if r["kind"] == "scenario")
    assert header["scenario"]["name"] == "smoke"
    assert Scenario.from_dict(header["scenario"]).turns == 3


def _corrupt_fuel(path: pathlib.Path, turn: int) -> None:
    lines = []
    for line in path.read_text().splitlines():
        record = json.loads(line)
        if record["kind"] == "state" and record["turn"] == turn:
            actor = min(record["state"]["actors"])
            record["state"]["actors"][actor]["fuel_days"] += 13.0
            # The digest is recomputed so the tampering is consistent: this
            # simulates a resolver that produced a different number, not a
            # corrupted file.
            from casus.state import WorldState

            record["digest"] = WorldState.from_json(record["state"]).digest()
        lines.append(json.dumps(record))
    path.write_text("\n".join(lines) + "\n")


# --- transcript completeness ------------------------------------------------


def test_every_action_is_recorded_after_the_response_that_produced_it(tmp_path):
    out = tmp_path / "run.jsonl"
    engine.run(_scenario(), seed=1, out=out, call=_scripted(), turns=2)
    kinds = [r["kind"] for r in _records(out)]
    for index, kind in enumerate(kinds):
        if kind == "action":
            assert "response" in kinds[:index], "an action appeared before any completion"


def test_every_prompt_is_recorded_before_its_response(tmp_path):
    out = tmp_path / "run.jsonl"
    engine.run(_scenario(), seed=1, out=out, call=_scripted(), turns=2)
    pairs = [r for r in _records(out) if r["kind"] in ("prompt", "response")]
    assert pairs, "no calls were recorded at all"
    for first, second in zip(pairs[::2], pairs[1::2], strict=True):
        assert first["kind"] == "prompt" and second["kind"] == "response"
        assert first["actor"] == second["actor"]


def test_a_retry_produces_two_recorded_prompt_response_pairs(tmp_path):
    """A player that has to retry must leave both exchanges on disk, or the
    transcript would not explain what the audience is looking at."""
    seen = {"calls": 0}

    def flaky(model, messages, schema=None, temperature=0.7) -> LLMResult:
        seen["calls"] += 1
        text = (
            "let me think about this"
            if seen["calls"] == 1
            else '{"actions":[{"type":"hold"}],"rationale":"r","assessment":"a"}'
        )
        return LLMResult(text=text, raw={}, model=model, prompt_tokens=1, completion_tokens=1)

    out = tmp_path / "run.jsonl"
    engine.run(_scenario(), seed=1, out=out, call=flaky, turns=1)
    records = _records(out)
    first_actor = next(r["actor"] for r in records if r["kind"] == "prompt")
    prompts = [r for r in records if r["kind"] == "prompt" and r["actor"] == first_actor]
    assert len(prompts) == 2
    assert "valid JSON" in prompts[1]["messages"][-1]["content"]


def test_the_prompt_the_model_saw_travels_with_the_action(tmp_path):
    out = tmp_path / "run.jsonl"
    engine.run(_scenario(), seed=1, out=out, call=_scripted(), turns=1)
    action = next(r for r in _records(out) if r["kind"] == "action")
    assert "YOUR STANDING ORDERS" in action["prompt"]
    assert action["rationale"]


def test_resolutions_are_recorded_against_the_turn_that_produced_them(tmp_path):
    out = tmp_path / "run.jsonl"
    engine.run(
        _scenario(),
        seed=1,
        out=out,
        call=_scripted(
            {
                "BLUE": '{"actions":[{"type":"blockade","region":"strait"}],'
                '"rationale":"squeeze","assessment":"they fold"}'
            }
        ),
        turns=1,
    )
    records = _records(out)
    turn_one = engine.resolutions_of(records, 1)
    assert any(r.kind == "escalation" and r.actor == "BLUE" for r in turn_one)


def test_the_end_record_carries_the_token_totals(tmp_path):
    out = tmp_path / "run.jsonl"
    summary = engine.run(_scenario(), seed=1, out=out, call=_scripted(), turns=2)
    end = next(r for r in _records(out) if r["kind"] == "end")
    assert end["prompt_tokens"] == summary.prompt_tokens > 0
    assert end["completion_tokens"] == summary.completion_tokens > 0


def test_an_unknown_record_kind_is_rejected_at_the_writer(tmp_path):
    """The replayer keys on `kind`, so a typo there would silently drop data."""
    transcript = engine._Transcript(tmp_path / "t.jsonl")
    with pytest.raises(AssertionError, match="unknown record kind"):
        transcript.write({"kind": "musings", "turn": 1})
    transcript.close()


# --- the loop itself --------------------------------------------------------


def test_run_plays_the_requested_number_of_turns(tmp_path):
    summary = engine.run(
        _scenario(), seed=1, out=tmp_path / "r.jsonl", call=_scripted(), turns=4
    )
    assert summary.turns == 4
    assert summary.final.turn == 5


def test_actors_are_polled_in_a_stable_order(tmp_path):
    out = tmp_path / "run.jsonl"
    engine.run(_scenario(), seed=1, out=out, call=_scripted(), turns=2)
    order = [r["actor"] for r in _records(out) if r["kind"] == "prompt"]
    assert order == sorted(order[:2]) * 2


def test_two_runs_with_the_same_seed_and_script_are_identical(tmp_path):
    a = engine.run(_scenario(), seed=5, out=tmp_path / "a.jsonl", call=_scripted(), turns=3)
    b = engine.run(_scenario(), seed=5, out=tmp_path / "b.jsonl", call=_scripted(), turns=3)
    assert [s.digest() for s in a.states] == [s.digest() for s in b.states]


def test_a_narrator_is_optional_and_recorded_when_present(tmp_path):
    out = tmp_path / "run.jsonl"
    engine.run(
        _scenario(),
        seed=1,
        out=out,
        call=_scripted(),
        narrate=lambda state, resolutions: f"turn {state.turn - 1} passed quietly",
        turns=1,
    )
    narrative = next(r for r in _records(out) if r["kind"] == "narrative")
    assert narrative["text"] == "turn 0 passed quietly" or "passed quietly" in narrative["text"]


def test_run_without_an_output_path_still_returns_a_summary():
    summary = engine.run(_scenario(), seed=1, out=None, call=_scripted(), turns=2)
    assert summary.transcript is None
    assert summary.turns == 2
