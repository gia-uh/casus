"""The turn loop, the transcript, the ledger inside it, and replay."""

import copy
import json

import pytest
from scenariopaths import SCENARIOS

from casus import engine
from casus.scenario import Scenario
from casus.state import Action, WorldState
from helpers import FakeEngine, scripted

SMOKE = SCENARIOS / "smoke"

RAIDING = scripted(
    {
        "BLUE": {
            "actions": [{"type": "raid", "place": "border", "intensity": 3}],
            "rationale": "push",
            "assessment": "they hold",
        }
    }
)


def _smoke() -> Scenario:
    return Scenario.load(SMOKE)


def _engines(scenario=None, reply=RAIDING):
    return {a: FakeEngine(reply) for a in (scenario or _smoke()).actors}


def _records(path) -> list[dict]:
    return engine.read_records(path)


def _run(out=None, seed=42, turns=3, reply=RAIDING, **kwargs):
    scenario = _smoke()
    return engine.run(
        scenario, seed=seed, out=out, engines=_engines(scenario, reply), turns=turns, **kwargs
    )


# --- the ledger ---------------------------------------------------------------


def test_the_transcript_carries_every_mutation_with_its_rule(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(out, turns=2)
    mutations = [r for r in _records(out) if r["kind"] == "mutation"]
    assert mutations
    assert all({"rule", "ref", "before", "after", "phase"} <= set(m) for m in mutations)
    assert {m["rule"] for m in mutations} >= {"raid", "upkeep"}


def _apply(state: dict, mutation: dict) -> None:
    scope, ident, *rest = mutation["ref"].split(".", 2)
    if scope == "entity" and not rest:
        entities = state["entities"]
        if mutation["after"] is None:
            entities[:] = [e for e in entities if e["id"] != ident]
        else:
            entities.append(copy.deepcopy(mutation["after"]))
        return
    (name,) = rest
    if scope == "actor":
        state["actors"][ident]["resources"][name] = mutation["after"]
    elif scope == "place":
        state["places"][ident]["attrs"][name] = mutation["after"]
    elif name == "place":
        next(e for e in state["entities"] if e["id"] == ident)["place"] = mutation["after"]
    else:
        next(e for e in state["entities"] if e["id"] == ident)["attrs"][name] = mutation["after"]


def _without_bookkeeping(state: dict) -> dict:
    return {k: v for k, v in state.items() if k not in ("turn", "events")}


def test_the_ledger_reconstructs_the_final_value_of_every_quantity(tmp_path):
    """If replaying the ledger does not land on the recorded state, some path
    changed a value without recording it, and the ledger is decoration."""
    out = tmp_path / "run.jsonl"
    _run(out, turns=4)
    records = _records(out)
    states = [r["state"] for r in records if r["kind"] == "state"]
    rebuilt = copy.deepcopy(states[0])
    for mutation in (r for r in records if r["kind"] == "mutation"):
        _apply(rebuilt, mutation)
    assert _without_bookkeeping(rebuilt) == _without_bookkeeping(states[-1])


# --- replay fidelity ------------------------------------------------------------


def test_replay_reproduces_the_state_trajectory_exactly(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(out)
    recorded = [r for r in _records(out) if r["kind"] == "state"]
    replayed = engine.replay(out).states
    assert len(recorded) == len(replayed) == 4  # initial state plus three turns
    assert [r["digest"] for r in recorded] == [s.digest() for s in replayed]


def _rewrite(path, change):
    records = [change(r) for r in _records(path)]
    path.write_text("\n".join(json.dumps(r) for r in records if r is not None) + "\n")


def test_replay_fails_loudly_when_a_recorded_state_was_tampered_with(tmp_path):
    """Break it on purpose. A verification that cannot fail is worth less than
    none, because it licenses shipping."""
    out = tmp_path / "run.jsonl"
    _run(out)

    def tamper(record):
        if record["kind"] == "state" and record["turn"] == 2:
            record["state"]["actors"]["BLUE"]["resources"]["stamina"] += 1.0
        return record

    _rewrite(out, tamper)
    with pytest.raises(engine.ReplayMismatch) as excinfo:
        engine.replay(out)
    assert "turn 2" in str(excinfo.value)
    assert "stamina" in str(excinfo.value)


def test_replay_fails_when_the_declarations_run_out(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(out)
    _rewrite(out, lambda r: None if r["kind"] == "declaration" and r["turn"] > 1 else r)
    with pytest.raises(engine.ReplayMismatch, match="ran out of recorded declarations"):
        engine.replay(out)


def test_replay_needs_nothing_but_the_transcript(tmp_path):
    """The rules travel inside the transcript, so replay reads no scenario file."""
    out = tmp_path / "run.jsonl"
    _run(out, turns=2)
    header = next(r for r in _records(out) if r["kind"] == "scenario")
    assert header["scenario"]["name"] == "smoke"
    assert "@rule" in header["rules_source"]
    rebuilt = Scenario.from_parts(header["scenario"], header["rules_source"])
    assert rebuilt.initial_state().digest() == _smoke().initial_state().digest()


def test_replay_on_rederives_a_run_against_a_scenario_implementation(tmp_path):
    out = tmp_path / "run.jsonl"
    summary = _run(out)
    replayed = engine.replay_on(_smoke(), out, translate=Action.from_json)
    assert [s.digest() for s in replayed.states] == [s.digest() for s in summary.states]


# --- what the transcript records --------------------------------------------


def test_the_prompt_is_recorded_before_the_declaration_it_produced(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(out, turns=1)
    kinds = [r["kind"] for r in _records(out)]
    assert kinds.index("prompt") < kinds.index("declaration")


def test_the_prompt_records_what_the_actor_was_offered(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(out, turns=1)
    prompt = next(r for r in _records(out) if r["kind"] == "prompt" and r["actor"] == "BLUE")
    assert "raid" in prompt["offered"]


def test_the_prompt_the_model_saw_travels_with_the_action(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(out, turns=1)
    action = next(r for r in _records(out) if r["kind"] == "action" and r["actor"] == "BLUE")
    assert action["prompt"].startswith("TURN 1.")
    assert action["action"]["type"] == "raid"


def test_events_are_recorded_against_the_turn_that_produced_them(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(out, turns=2)
    raided = [r for r in _records(out) if r["kind"] == "event" and r["event"]["id"] == "raided"]
    assert [r["turn"] for r in raided] == [1, 2]


def test_run_plays_the_requested_number_of_turns():
    summary = _run(turns=2)
    assert summary.turns == 2
    assert summary.final.turn == 3


def test_prompts_are_written_in_a_stable_actor_order(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(out, turns=1)
    actors = [r["actor"] for r in _records(out) if r["kind"] == "prompt"]
    assert actors == sorted(actors)


def test_two_runs_with_the_same_seed_and_script_are_identical():
    assert [s.digest() for s in _run(seed=9).states] == [s.digest() for s in _run(seed=9).states]


def test_a_narrator_is_optional_and_recorded_when_present(tmp_path):
    out = tmp_path / "run.jsonl"
    _run(
        out,
        turns=1,
        narrator_engine=FakeEngine(lambda prompt: {"predicates": ["raided"] * _facts(prompt)}),
    )
    narrative = next(r for r in _records(out) if r["kind"] == "narrative")
    assert narrative["text"].startswith("Blue raided")


def _facts(prompt: str) -> int:
    block = prompt.split("Standing position")[0]
    return sum(1 for line in block.splitlines() if line.strip()[:2].rstrip(".").isdigit())


def test_a_rule_that_raises_is_recorded_and_the_run_stops(tmp_path):
    """Review Focus 5: the run must not die silently mid-turn."""
    scenario = _smoke()
    broken = Scenario.from_parts(
        scenario.data,
        scenario.rules_source
        + "\n\n@rule(phase='contest')\ndef broken(s):\n    s.place('atlantis')\n",
    )
    out = tmp_path / "run.jsonl"
    with pytest.raises(engine.RuleFailed):
        engine.run(broken, seed=1, out=out, engines=_engines(broken), turns=2)
    records = _records(out)
    (error,) = [r for r in records if r["kind"] == "error"]
    assert "broken" in error["error"] and "atlantis" in error["error"]
    assert [r["turn"] for r in records if r["kind"] == "state"] == [1]


def test_run_without_an_output_path_still_returns_a_summary():
    summary = _run(turns=1)
    assert isinstance(summary.final, WorldState)
