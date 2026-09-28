"""The narrator reads the world and writes about it. It cannot change it, and it
cannot say who did what."""

import asyncio
import random

import pytest
from pydantic import ValidationError

from casus import narrator, rules
from casus.state import Action, Resolution
from helpers import FakeEngine, make_region, make_world


def _predicates(*texts):
    return {"predicates": list(texts)}


def _narrate(world, resolutions=(), engine=None, language="en"):
    resolutions = list(resolutions)
    if engine is None:
        engine = FakeEngine(
            _predicates(*["did something"] * len(narrator.reportable(resolutions)))
        )
    return asyncio.run(narrator.narrate(world, resolutions, engine, language)), engine


def _fact(kind="supply_delivered", actor="ATK", reason="moved fuel"):
    return Resolution(kind=kind, actor=actor, reason=reason)


# --- the invariant this module exists for -----------------------------------


def test_narrator_cannot_mutate_state(world):
    before = world.digest()
    _narrate(world, [_fact()])
    assert world.digest() == before


def test_narrator_returns_a_string_and_nothing_else(world):
    text, _ = _narrate(world, [_fact()])
    assert isinstance(text, str)


# --- the model does not choose the subject ----------------------------------


def test_the_engine_supplies_the_subject_from_the_record(world):
    """Letting the model name the actor produced three misattributions in twelve
    dispatches — an American air campaign reported as Cuban, twice."""
    text, _ = _narrate(
        world,
        [_fact(actor="ATK", reason="an air campaign")],
        engine=FakeEngine(_predicates("conducted an air campaign")),
    )
    assert text == f"{world.actors['ATK'].name} conducted an air campaign."


def test_two_facts_keep_their_own_subjects_in_order(world):
    text, _ = _narrate(
        world,
        [_fact(actor="ATK", reason="one"), _fact(actor="DEF", reason="two")],
        engine=FakeEngine(_predicates("struck first", "dug in")),
    )
    assert text == (
        f"{world.actors['ATK'].name} struck first. {world.actors['DEF'].name} dug in."
    )


def test_a_short_list_of_predicates_is_refused_rather_than_shifting_every_subject(world):
    """Four predicates for five facts would shift every subject by one, and it
    would look entirely plausible on screen."""
    facts = [_fact(actor="ATK"), _fact(actor="DEF")]
    with pytest.raises(ValidationError):
        _narrate(world, facts, engine=FakeEngine(_predicates("only one")))


def test_a_long_list_of_predicates_is_refused_too(world):
    with pytest.raises(ValidationError):
        _narrate(world, [_fact()], engine=FakeEngine(_predicates("one", "two")))


def test_a_fact_with_no_actor_gets_no_invented_subject(world):
    text, _ = _narrate(
        world,
        [Resolution(kind="unopposed", actor=None, reason="nobody was there")],
        engine=FakeEngine(_predicates("the airspace was empty")),
    )
    assert text == "the airspace was empty."


def test_an_empty_predicate_is_dropped(world):
    text, _ = _narrate(
        world,
        [_fact(actor="ATK"), _fact(actor="DEF")],
        engine=FakeEngine(_predicates("   ", "held the line")),
    )
    assert text == f"{world.actors['DEF'].name} held the line."


def test_a_fragment_gets_terminal_punctuation(world):
    text, _ = _narrate(world, [_fact()], engine=FakeEngine(_predicates("turned back")))
    assert text.endswith(".")


# --- what the correspondent is told -----------------------------------------


def test_the_prompt_numbers_the_facts_so_the_pairing_is_visible(world):
    _, engine = _narrate(world, [_fact(reason="the island ran dry")])
    assert "1. [supply_delivered]: the island ran dry" in engine.prompts[0]


def test_the_prompt_does_not_name_the_actor_beside_the_fact(world):
    """Naming it beside the fact is exactly what invited the model to re-use the
    wrong one."""
    _, engine = _narrate(world, [_fact(actor="ATK", reason="moved fuel")])
    facts_block = engine.prompts[0].split("Standing position")[0]
    assert "ATK" not in facts_block


def test_bookkeeping_events_are_kept_out_of_the_news(world):
    text, _ = _narrate(world, [Resolution(kind="escalation", actor="ATK", reason="rung 6")])
    assert text == ""


def test_a_turn_with_nothing_to_report_costs_no_model_call(world):
    engine = FakeEngine(_predicates())
    text = asyncio.run(narrator.narrate(world, [], engine))
    assert text == ""
    assert engine.prompts == []


def test_only_the_first_few_facts_are_reported(world):
    facts = [_fact(reason=f"thing {i}") for i in range(12)]
    assert len(narrator.reportable(facts)) == narrator.MAX_FACTS


def test_empty_sea_zones_are_left_out_of_the_civilian_summary():
    world = make_world(
        regions={
            "capital": make_region("capital", "DEF", name="Capital", population=1_200_000),
            "sea-1": make_region("sea-1", "", name="Open sea", terrain="sea", population=0),
        }
    )
    _, engine = _narrate(world, [_fact()])
    assert "Capital" in engine.prompts[0]
    assert "Open sea" not in engine.prompts[0]


def test_the_language_instruction_lands_at_the_end_of_the_user_message(world):
    _, engine = _narrate(world, [_fact()], language="es")
    assert engine.prompts[0].rstrip().endswith("common form in that language.")
    assert "Spanish" in engine.prompts[0]


def test_english_adds_no_language_instruction(world):
    _, engine = _narrate(world, [_fact()], language="en")
    assert "Write them in" not in engine.prompts[0]


def test_the_dispatch_describes_the_turn_that_just_resolved():
    """The state handed to the narrator has already been advanced, so the day
    being reported is one behind the state's turn counter."""
    state = make_world(turn=5)
    resolved, _ = rules.resolve(state, [Action(actor="ATK", type="sanction")], random.Random(1))
    _, engine = _narrate(resolved, [_fact()])
    assert engine.prompts[0].startswith("DAY 5.")
