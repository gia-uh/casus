"""The narrator reads the world and writes about it. It cannot change it."""

import asyncio
import random

from casus import narrator, rules
from casus.state import Action, Resolution
from helpers import FakeEngine, make_region, make_world


def _dispatch(lines):
    return {"lines": lines}


def _narrate(world, resolutions=(), engine=None):
    engine = engine or FakeEngine(_dispatch([{"actor": "ATK", "text": "Quiet day."}]))
    return asyncio.run(narrator.narrate(world, list(resolutions), engine)), engine


# --- the invariant this module exists for -----------------------------------


def test_narrator_cannot_mutate_state(world):
    before = world.digest()
    _narrate(world)
    assert world.digest() == before


def test_narrator_returns_a_string_and_nothing_else(world):
    text, _ = _narrate(world)
    assert isinstance(text, str)


def test_a_dispatch_can_only_be_attributed_to_an_actor_that_exists(world):
    """In the first Caribbean run the narrator credited an action to the wrong
    country. An enum cannot stop it choosing wrongly, but it stops it inventing
    a party that is not in the game."""
    schema = narrator.dispatch_model(tuple(sorted(world.actors)))
    line = next(iter(schema.model_json_schema()["$defs"].values()))
    assert line["properties"]["actor"]["enum"] == sorted(world.actors)


def test_the_dispatch_is_capped_so_it_cannot_run_away(world):
    schema = narrator.dispatch_model(tuple(sorted(world.actors)))
    assert schema.model_json_schema()["properties"]["lines"]["maxItems"] == narrator.MAX_LINES


def test_every_line_is_attributed_in_the_rendered_text(world):
    text, _ = _narrate(
        world,
        engine=FakeEngine(
            _dispatch(
                [
                    {"actor": "ATK", "text": "Tankers turned back."},
                    {"actor": "DEF", "text": "The island dug in."},
                ]
            )
        ),
    )
    assert "ATK: Tankers turned back." in text
    assert "DEF: The island dug in." in text


def test_an_empty_line_is_dropped_rather_than_printed_bare(world):
    text, _ = _narrate(
        world,
        engine=FakeEngine(
            _dispatch([{"actor": "ATK", "text": "  "}, {"actor": "DEF", "text": "Held."}])
        ),
    )
    assert text == "DEF: Held."


# --- what the correspondent is told -----------------------------------------


def test_the_prompt_carries_the_resolutions_verbatim(world):
    _, engine = _narrate(
        world, [Resolution(kind="fuel_exhausted", actor="DEF", reason="the island ran dry")]
    )
    assert "the island ran dry" in engine.prompts[0]
    assert "fuel_exhausted" in engine.prompts[0]


def test_bookkeeping_events_are_kept_out_of_the_news(world):
    _, engine = _narrate(
        world, [Resolution(kind="escalation", actor="ATK", reason="reached rung 6")]
    )
    assert "reached rung 6" not in engine.prompts[0]
    assert "Nothing material was resolved" in engine.prompts[0]


def test_an_empty_turn_is_described_as_such(world):
    _, engine = _narrate(world)
    assert "Nothing material was resolved" in engine.prompts[0]


def test_the_prompt_names_every_actor_by_identifier(world):
    _, engine = _narrate(world)
    for actor_id in world.actors:
        assert f"  {actor_id} (" in engine.prompts[0]


def test_empty_sea_zones_are_left_out_of_the_civilian_summary():
    world = make_world(
        regions={
            "capital": make_region("capital", "DEF", name="Capital", population=1_200_000),
            "sea-1": make_region("sea-1", "", name="Open sea", terrain="sea", population=0),
        }
    )
    _, engine = _narrate(world)
    assert "Capital" in engine.prompts[0]
    assert "Open sea" not in engine.prompts[0]


def test_the_dispatch_describes_the_turn_that_just_resolved():
    """The state handed to the narrator has already been advanced, so the day
    being reported is one behind the state's turn counter."""
    state = make_world(turn=5)
    resolved, resolutions = rules.resolve(
        state, [Action(actor="ATK", type="sanction")], random.Random(1)
    )
    _, engine = _narrate(resolved, resolutions)
    assert engine.prompts[0].startswith("DAY 5.")
