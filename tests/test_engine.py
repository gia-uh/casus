import json
import pathlib

import pytest

from casus import engine
from casus.scenario import Scenario
from helpers import FakeEngine, scripted

SMOKE = pathlib.Path(__file__).parent.parent / "scenarios" / "smoke.yaml"


def _scenario() -> Scenario:
    return Scenario.load(SMOKE)


def _engines(scenario, reply=None):
    return {a: FakeEngine(reply) for a in scenario.actors}


def _records(path) -> list[dict]:
    return engine.read_records(path)


def _run(scenario, out=None, reply=None, seed=42, turns=3):
    return engine.run(
        scenario, seed=seed, out=out, engines=_engines(scenario, reply), turns=turns
    )


# --- replay fidelity, the claim the whole design rests on -------------------


def test_replay_reproduces_the_state_trajectory_exactly(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(_scenario(), out)
    recorded = [r for r in _records(out) if r["kind"] == "state"]
    replayed = engine.replay(out).states
    assert len(recorded) == len(replayed) == 4  # initial state plus three turns
    assert [r["digest"] for r in recorded] == [s.digest() for s in replayed]


def test_replay_fails_loudly_when_a_recorded_state_was_tampered_with(tmp_path):
    """Break it on purpose. A verification that cannot fail is worth less than
    none, because it licenses shipping."""
    out = tmp_path / "run.jsonl"
    _run(_scenario(), out)
    _corrupt_fuel(out, turn=2)

    with pytest.raises(engine.ReplayMismatch) as excinfo:
        engine.replay(out)
    assert "turn 2" in str(excinfo.value)
    assert "fuel_days" in str(excinfo.value)


def test_replay_fails_when_the_declarations_run_out(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(_scenario(), out)
    kept = [r for r in _records(out) if not (r["kind"] == "declaration" and r["turn"] > 1)]
    out.write_text("\n".join(json.dumps(r) for r in kept) + "\n")
    with pytest.raises(engine.ReplayMismatch, match="ran out of recorded declarations"):
        engine.replay(out)


def test_replay_needs_nothing_but_the_transcript(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(_scenario(), out, seed=7, turns=2)
    header = next(r for r in _records(out) if r["kind"] == "scenario")
    assert header["scenario"]["name"] == "smoke"
    assert Scenario.from_dict(header["scenario"]).turns == 3


def _corrupt_fuel(path: pathlib.Path, turn: int) -> None:
    from casus.v1.state import WorldState

    lines = []
    for line in path.read_text().splitlines():
        record = json.loads(line)
        if record["kind"] == "state" and record["turn"] == turn:
            actor = min(record["state"]["actors"])
            record["state"]["actors"][actor]["fuel_days"] += 13.0
            # The digest is recomputed so the tampering is consistent: this
            # simulates a resolver that produced a different number, not a
            # corrupted file.
            record["digest"] = WorldState.from_json(record["state"]).digest()
        lines.append(json.dumps(record))
    path.write_text("\n".join(lines) + "\n")


# --- transcript completeness ------------------------------------------------


def test_the_prompt_is_recorded_before_the_declaration_it_produced(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(_scenario(), out, turns=2)
    kinds = [r["kind"] for r in _records(out)]
    for index, kind in enumerate(kinds):
        if kind == "declaration":
            assert "prompt" in kinds[:index], "a declaration appeared before any prompt"


def test_the_prompt_the_model_saw_travels_with_the_action(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(_scenario(), out, turns=1)
    action = next(r for r in _records(out) if r["kind"] == "action")
    assert "YOUR STANDING ORDERS" in action["prompt"]
    assert action["rationale"]


def test_resolutions_are_recorded_against_the_turn_that_produced_them(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(
        _scenario(),
        out,
        reply=scripted(
            {
                "BLUE": {
                    "actions": [{"type": "blockade", "region": "strait"}],
                    "rationale": "squeeze",
                    "assessment": "they fold",
                }
            }
        ),
        turns=1,
    )
    turn_one = engine.resolutions_of(_records(out), 1)
    assert any(r.kind == "escalation" and r.actor == "BLUE" for r in turn_one)


def test_an_unknown_record_kind_is_rejected_at_the_writer(tmp_path):
    """The replayer keys on `kind`, so a typo there would silently drop data."""
    transcript = engine._Transcript(tmp_path / "t.jsonl")
    with pytest.raises(AssertionError, match="unknown record kind"):
        transcript.write({"kind": "musings", "turn": 1})
    transcript.close()


# --- the loop itself --------------------------------------------------------


def test_run_plays_the_requested_number_of_turns(tmp_path):
    summary = _run(_scenario(), tmp_path / "r.jsonl", turns=4)
    assert summary.turns == 4
    assert summary.final.turn == 5


def test_prompts_are_written_in_a_stable_actor_order(tmp_path):
    """The calls go out together, so the transcript order has to come from the
    actor list rather than from whichever reply lands first."""
    out = tmp_path / "run.jsonl"
    _run(_scenario(), out, turns=2)
    order = [r["actor"] for r in _records(out) if r["kind"] == "prompt"]
    assert order == sorted(order[:2]) * 2


def test_two_runs_with_the_same_seed_and_script_are_identical(tmp_path):
    a = _run(_scenario(), tmp_path / "a.jsonl", seed=5)
    b = _run(_scenario(), tmp_path / "b.jsonl", seed=5)
    assert [s.digest() for s in a.states] == [s.digest() for s in b.states]


def test_a_narrator_is_optional_and_recorded_when_present(tmp_path):
    """The correspondent returns one predicate per reportable fact, so the fake
    answers with however many the turn actually produced."""
    out = tmp_path / "run.jsonl"
    scenario = _scenario()
    engine.run(
        scenario,
        seed=1,
        out=out,
        engines=_engines(
            scenario,
            scripted(
                {
                    "BLUE": {
                        "actions": [{"type": "mobilize", "region": "b-coast"}],
                        "rationale": "call up",
                        "assessment": "",
                    }
                }
            ),
        ),
        narrator_engine=FakeEngine(
            lambda prompt: {"predicates": ["called up reserves"] * _facts(prompt)}
        ),
        turns=1,
    )
    narrative = next(r for r in _records(out) if r["kind"] == "narrative")
    assert "called up reserves" in narrative["text"]
    # the subject comes from the record, not from the model
    assert narrative["text"].startswith("Blue ")


def _facts(prompt: str) -> int:
    """How many numbered facts the correspondent was given."""
    block = prompt.split("Standing position")[0]
    return sum(1 for line in block.splitlines() if line.strip()[:2].rstrip(".").isdigit())


def test_run_without_an_output_path_still_returns_a_summary():
    summary = _run(_scenario(), None, turns=2)
    assert summary.transcript is None
    assert summary.turns == 2
