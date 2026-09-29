"""The narrator reads the world and writes about it. It cannot change it, and it
cannot say who did what."""

import asyncio

import pytest
from pydantic import ValidationError
from scenariopaths import SCENARIOS

from casus import display, narrator
from casus.scenario import Scenario
from casus.state import Event
from helpers import FakeEngine

SMOKE = Scenario.load(SCENARIOS / "smoke")
WORLD = SMOKE.initial_state()
NAMES = {a.id: a.name for a in WORLD.actors.values()}


def _predicates(*texts):
    return {"predicates": list(texts)}


def _scenario(**display_overrides):
    data = {**SMOKE.data, "display": {**SMOKE.display, **display_overrides}}
    return Scenario.from_parts(data, SMOKE.rules_source)


def _spanish_scenario_with_label(actor_id: str, label: str):
    data = {
        **SMOKE.data,
        "language": "es",
        "display": {**SMOKE.display, "labels": {"es": {actor_id: label}}},
    }
    scenario = Scenario.from_parts(data, SMOKE.rules_source)
    return scenario, scenario.initial_state()


def _engine_replying(predicates: list[str]):
    return FakeEngine({"predicates": predicates})


def _narrate(events=(), engine=None, scenario=SMOKE, world=WORLD):
    events = list(events)
    if engine is None:
        count = len(narrator.reportable(events, scenario))
        engine = FakeEngine(_predicates(*["did something"] * count))
    return asyncio.run(narrator.narrate(world, events, engine, scenario)), engine


def _fact(ident="raided", actor="BLUE", reason="it burned", place=None):
    return Event(ident, {"actor": actor, "reason": reason, "place": place})


def test_narrator_cannot_mutate_state():
    before = WORLD.digest()
    _narrate([_fact()])
    assert WORLD.digest() == before


def test_the_engine_supplies_the_subject_from_the_record():
    text, _ = _narrate([_fact(actor="BLUE")], engine=FakeEngine(_predicates("raided the border")))
    assert text == f"{NAMES['BLUE']} raided the border."


def test_two_facts_keep_their_own_subjects_in_order():
    text, _ = _narrate(
        [_fact(actor="BLUE"), _fact(actor="RED")],
        engine=FakeEngine(_predicates("struck first", "dug in")),
    )
    assert text == f"{NAMES['BLUE']} struck first. {NAMES['RED']} dug in."


def test_a_short_list_of_predicates_is_refused_rather_than_shifting_every_subject():
    with pytest.raises(ValidationError):
        _narrate([_fact(), _fact(actor="RED")], engine=FakeEngine(_predicates("only one")))


def test_a_long_list_of_predicates_is_refused_too():
    with pytest.raises(ValidationError):
        _narrate([_fact()], engine=FakeEngine(_predicates("one", "two")))


def test_a_fact_with_no_actor_gets_no_invented_subject():
    text, _ = _narrate(
        [Event("quiet", {"reason": "nothing moved"})],
        engine=FakeEngine(_predicates("the border was quiet")),
    )
    assert text == "the border was quiet."


def test_an_empty_predicate_is_dropped():
    text, _ = _narrate(
        [_fact(actor="BLUE"), _fact(actor="RED")],
        engine=FakeEngine(_predicates("   ", "held the line")),
    )
    assert text == f"{NAMES['RED']} held the line."


def test_the_prompt_numbers_the_facts_so_the_pairing_is_visible():
    _, engine = _narrate([_fact(reason="the depot burned", place="border")])
    assert "1. [raided] in border: the depot burned" in engine.prompts[0]


def test_the_prompt_does_not_name_the_actor_beside_the_fact():
    _, engine = _narrate([_fact(actor="BLUE")])
    assert "BLUE" not in engine.prompts[0].split("Standing position")[0]


def test_events_the_scenario_marks_unreported_stay_out_of_the_news():
    text, _ = _narrate([_fact(ident="escalation")], scenario=_scenario(unreported=["escalation"]))
    assert text == ""


def test_a_turn_with_nothing_to_report_costs_no_model_call():
    engine = FakeEngine(_predicates())
    text = asyncio.run(narrator.narrate(WORLD, [], engine, SMOKE))
    assert (text, engine.prompts) == ("", [])


def test_only_the_first_few_facts_are_reported():
    facts = [_fact(reason=f"thing {i}") for i in range(12)]
    assert len(narrator.reportable(facts, SMOKE)) == narrator.MAX_FACTS


def test_the_standing_position_uses_the_display_labels_and_hides_coordinates():
    _, engine = _narrate([_fact()])
    standing = engine.prompts[0].split("Standing position")[1]
    assert "stamina" in standing
    assert "lat" not in standing and "lon" not in standing


def test_the_language_instruction_lands_at_the_end_of_the_user_message():
    spanish = Scenario.from_parts({**SMOKE.data, "language": "es"}, SMOKE.rules_source)
    _, engine = _narrate([_fact()], scenario=spanish)
    assert engine.prompts[0].rstrip().endswith("common form in that language.")
    assert "Spanish" in engine.prompts[0]


def test_the_dispatch_describes_the_turn_that_just_resolved():
    """The state handed to the narrator has already been advanced, so the day
    being reported is one behind the state's turn counter."""
    import dataclasses

    _, engine = _narrate([_fact()], world=dataclasses.replace(WORLD, turn=6))
    assert engine.prompts[0].startswith("DAY 5.")


def test_the_subject_is_the_actor_label_in_the_scenario_language():
    """The narrator wrote 'Third parties transferido…' because it used the
    actor's English name in front of a Spanish predicate."""
    scenario, world = _spanish_scenario_with_label("BLUE", "Azules")
    fact = Event(id="resupplied", detail={"actor": "BLUE", "reason": "sent supplies"})
    engine = _engine_replying(["enviaron suministros"])
    text = asyncio.run(narrator.narrate(world, [fact], engine, scenario))
    assert text.startswith(display.actor_label(scenario, "BLUE") + " ")
