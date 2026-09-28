"""The point of these types is that the bad declarations cannot be written, and
that the vocabulary comes from the scenario rather than from a table.

Every unrepresentability test here is an attempt to express something the first
version of the harness accepted from a model and then rejected at the resolver.
"""

import pytest
from pydantic import ValidationError

from casus import actions
from casus.actions import MAX_ACTIONS_PER_TURN, declaration_model, to_actions
from casus.scenario import Scenario

PLACES = ("capital", "inland", "sea-1")

VOCABULARY = {
    "hold": {"fields": [], "description": "Take no action this turn."},
    "statement": {"fields": [], "description": "Make a public declaration."},
    "supply": {"fields": ["target"], "description": "Transfer fuel to another actor."},
    "strike": {
        "fields": ["place", "intensity"],
        "intensity": [1, 3],
        "description": {"en": "Hit a place.", "es": "Golpear un lugar."},
    },
    "deploy": {"fields": ["place", "entities"], "description": "Move named units."},
    "invade": {"fields": ["place", "intensity"], "intensity": [1, 3], "description": "Invade."},
}


def _scenario(vocabulary=None, language="en") -> Scenario:
    data = {
        "name": "vocabulary",
        "language": language,
        "actions": vocabulary or VOCABULARY,
        "actors": {
            a: {"name": a, "model": "m", "briefing": "b"} for a in ("ATK", "DEF", "THIRD")
        },
        "places": {p: {"name": p} for p in PLACES},
    }
    return Scenario.from_parts(data, "")


def _scenario_declaring(action_type, description_es=None) -> Scenario:
    spec = {"fields": ["place"], "description": f"{action_type} in English"}
    if description_es:
        spec["description"] = {"en": f"{action_type} in English", "es": description_es}
    return _scenario({action_type: spec}, language="es" if description_es else "en")


OFFERED = {"hold": None, "supply": None, "strike": PLACES, "statement": None}


def _declare(items, offered=None, actor="ATK"):
    model = declaration_model(actor, offered or OFFERED, _scenario())
    return model.model_validate(
        {"actions": items, "rationale": "because", "assessment": "wait"}
    )


def test_the_declaration_type_is_built_from_the_scenario_not_from_a_table():
    model = declaration_model("ATK", {"besiege": ("fort",)}, _scenario_declaring("besiege"))
    branch = next(iter(model.model_json_schema()["$defs"].values()))
    assert branch["properties"]["type"]["const"] == "besiege"
    assert branch["properties"]["place"]["enum"] == ["fort"]
    assert not hasattr(actions, "FIELDS"), "the hardcoded table is gone"


def test_the_action_description_is_localised_while_the_identifier_is_not():
    scenario = _scenario_declaring("air_campaign", description_es="campaña aérea sostenida")
    schema = declaration_model("ATK", {"air_campaign": ("x",)}, scenario).model_json_schema()
    branch = next(iter(schema["$defs"].values()))
    assert branch["description"] == "campaña aérea sostenida"
    assert branch["properties"]["type"]["const"] == "air_campaign"


def test_the_place_enum_is_what_offer_allows_not_the_whole_map():
    model = declaration_model("ATK", {"strike": ("inland",)}, _scenario())
    branch = next(iter(model.model_json_schema()["$defs"].values()))
    assert branch["properties"]["place"]["enum"] == ["inland"]


# --- the twenty-one per cent ------------------------------------------------


def test_a_supply_without_a_recipient_cannot_be_expressed():
    """Ten of seventeen rejections in the first Caribbean run were exactly this."""
    with pytest.raises(ValidationError):
        _declare([{"type": "supply"}])


def test_a_supply_aimed_at_a_place_cannot_be_expressed():
    with pytest.raises(ValidationError):
        _declare([{"type": "supply", "place": "capital"}])


def test_a_supply_names_an_actor_and_only_an_actor():
    (action,) = to_actions(_declare([{"type": "supply", "target": "DEF"}]), "ATK")
    assert (action.target, action.place) == ("DEF", None)


def test_an_actor_cannot_supply_itself():
    with pytest.raises(ValidationError):
        _declare([{"type": "supply", "target": "ATK"}])


def test_a_place_that_is_not_offered_cannot_be_expressed():
    with pytest.raises(ValidationError):
        _declare([{"type": "strike", "place": "atk-air-defense"}])


def test_an_invented_place_for_a_statement_cannot_be_expressed():
    """Both models kept inventing 'global' and 'international'."""
    with pytest.raises(ValidationError):
        _declare([{"type": "statement", "place": "global"}])


def test_an_action_type_that_was_not_offered_cannot_be_expressed():
    with pytest.raises(ValidationError):
        _declare([{"type": "invade", "place": "capital"}], offered={"hold": None})


def test_an_intensity_outside_the_declared_range_cannot_be_expressed():
    with pytest.raises(ValidationError):
        _declare([{"type": "strike", "place": "capital", "intensity": 1000}])


def test_more_than_the_maximum_actions_cannot_be_expressed():
    with pytest.raises(ValidationError):
        _declare([{"type": "hold"}] * (MAX_ACTIONS_PER_TURN + 1))


def test_an_empty_declaration_cannot_be_expressed():
    with pytest.raises(ValidationError):
        _declare([])


# --- what should still work -------------------------------------------------


def test_a_well_formed_declaration_converts_to_engine_actions():
    declared = to_actions(
        _declare([{"type": "strike", "place": "capital", "intensity": 2}, {"type": "hold"}]),
        "ATK",
    )
    assert [a.type for a in declared] == ["strike", "hold"]
    assert (declared[0].place, declared[0].intensity) == ("capital", 2)
    assert all(a.actor == "ATK" for a in declared)


def test_intensity_defaults_to_the_bottom_of_its_range():
    (action,) = to_actions(_declare([{"type": "strike", "place": "capital"}]), "ATK")
    assert action.intensity == 1


def test_deploy_carries_entity_identifiers():
    declaration = _declare(
        [{"type": "deploy", "place": "capital", "entities": ["atk-marines"]}],
        offered={"deploy": PLACES},
    )
    assert to_actions(declaration, "ATK")[0].entities == ("atk-marines",)


def test_every_declared_type_can_be_spoken_with_its_own_fields():
    """A type in the vocabulary that cannot actually be spoken is worse than one
    that is missing, because it fails silently at the far end."""
    for action_type, spec in VOCABULARY.items():
        payload: dict = {"type": action_type}
        if "place" in spec["fields"]:
            payload["place"] = "capital"
        if "target" in spec["fields"]:
            payload["target"] = "DEF"
        offered = {action_type: PLACES if "place" in spec["fields"] else None}
        assert to_actions(_declare([payload], offered), "ATK")[0].type == action_type


def test_building_a_model_with_nothing_offered_is_an_error_not_an_empty_union():
    with pytest.raises(ValueError, match="nothing to declare"):
        declaration_model("ATK", {}, _scenario())


def test_an_offered_type_the_scenario_never_declared_is_an_error():
    with pytest.raises(ValueError, match="teleport"):
        declaration_model("ATK", {"teleport": None}, _scenario())
