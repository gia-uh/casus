import random

from casus import narrator, rules
from casus.llm import LLMError, LLMResult
from casus.state import Action, Resolution
from helpers import make_region, make_world


def _returns(text: str):
    def call(model, messages, **kwargs):
        return LLMResult(
            text=text, raw={}, model=model or "m", prompt_tokens=1, completion_tokens=1
        )

    return call


def _capture(seen: dict, text: str = "Quiet day on the strait."):
    def call(model, messages, **kwargs):
        seen["system"] = messages[0]["content"]
        seen["prompt"] = messages[-1]["content"]
        return LLMResult(text=text, raw={}, model="m", prompt_tokens=1, completion_tokens=1)

    return call


# --- the invariant this module exists for -----------------------------------


def test_narrator_cannot_mutate_state(world):
    before = world.digest()
    narrator.narrate(world, [], call=_returns('{"set": {"CU": {"fuel_days": 999}}}'))
    assert world.digest() == before


def test_narrator_has_no_write_path_at_all(world):
    """Not just "it did not write this time": the signature returns a string, so
    there is nowhere for a state change to go."""
    result = narrator.narrate(world, [], call=_returns("Nothing happened."))
    assert isinstance(result, str)


def test_structured_output_is_refused_rather_than_passed_through(world):
    text = narrator.narrate(world, [], call=_returns('{"headline": "War!"}'))
    assert "structured data" in text
    assert "War!" not in text


def test_a_reasoning_block_is_stripped_from_the_dispatch(world):
    text = narrator.narrate(
        world, [], call=_returns("<think>what angle do I take</think>Tankers turned back.")
    )
    assert text == "Tankers turned back."


def test_a_failing_model_does_not_kill_the_run(world):
    """Narration is decoration. A run that dies because the correspondent timed
    out would be worse than a run with a missing paragraph."""

    def explodes(model, messages, **kwargs):
        raise LLMError("gateway timeout")

    text = narrator.narrate(world, [], call=explodes)
    assert "no dispatch" in text


# --- what the correspondent is told -----------------------------------------


def test_the_prompt_carries_the_resolutions_verbatim(world):
    seen: dict = {}
    narrator.narrate(
        world,
        [Resolution(kind="fuel_exhausted", actor="CU", reason="the island ran dry")],
        call=_capture(seen),
    )
    assert "the island ran dry" in seen["prompt"]
    assert "fuel_exhausted" in seen["prompt"]


def test_bookkeeping_events_are_kept_out_of_the_news(world):
    seen: dict = {}
    narrator.narrate(
        world,
        [
            Resolution(
                kind="escalation", actor="US", reason="reached rung 6 with 'air_campaign'"
            )
        ],
        call=_capture(seen),
    )
    assert "reached rung 6" not in seen["prompt"]
    assert "Nothing material was resolved" in seen["prompt"]


def test_an_empty_turn_is_described_as_such(world):
    seen: dict = {}
    narrator.narrate(world, [], call=_capture(seen))
    assert "Nothing material was resolved" in seen["prompt"]


def test_the_prompt_reports_the_standing_position_of_every_actor(world):
    seen: dict = {}
    narrator.narrate(world, [], call=_capture(seen))
    for actor_id in world.actors:
        assert actor_id in seen["prompt"]


def test_empty_sea_zones_are_left_out_of_the_civilian_summary():
    world = make_world(
        regions={
            "cu-havana": make_region("cu-havana", "CU", name="Havana", population=1_200_000),
            "sea-1": make_region("sea-1", "", name="Open sea", terrain="sea", population=0),
        }
    )
    seen: dict = {}
    narrator.narrate(world, [], call=_capture(seen))
    assert "Havana" in seen["prompt"]
    assert "Open sea" not in seen["prompt"]


def test_the_correspondent_is_told_not_to_invent_numbers(world):
    seen: dict = {}
    narrator.narrate(world, [], call=_capture(seen))
    assert "no invented numbers" in seen["system"]


def test_the_dispatch_describes_the_turn_that_just_resolved():
    """The state handed to the narrator has already been advanced, so the day
    being reported is one behind the state's turn counter."""
    state = make_world(turn=5)
    resolved, resolutions = rules.resolve(
        state, [Action(actor="US", type="sanction")], random.Random(1)
    )
    seen: dict = {}
    narrator.narrate(resolved, resolutions, call=_capture(seen))
    assert seen["prompt"].startswith("DAY 5.")
