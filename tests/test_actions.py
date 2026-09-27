"""The point of these types is that the bad declarations cannot be written.

Every test here is an attempt to express something the first version of the
harness accepted from a model and then rejected at the resolver.
"""

import pytest
from pydantic import ValidationError

from casus import rules
from casus.actions import (
    DESCRIPTIONS,
    FIELDS,
    MAX_ACTIONS_PER_TURN,
    declaration_model,
    to_actions,
    vocabulary_matches_the_engine,
)
from casus.state import ACTION_TYPES

REGIONS = ("capital", "inland", "sea-1")
ACTORS = ("ATK", "DEF", "THIRD")


def _model(legal=("hold", "supply", "strike", "statement"), actor="ATK"):
    return declaration_model(actor, tuple(legal), REGIONS, ACTORS)


def _declare(actions, legal=("hold", "supply", "strike", "statement"), actor="ATK"):
    return _model(legal, actor).model_validate(
        {"actions": actions, "rationale": "because", "assessment": "they wait"}
    )


# --- the twenty-one per cent ------------------------------------------------


def test_a_supply_without_a_recipient_cannot_be_expressed():
    """Ten of seventeen rejections in the first Caribbean run were exactly this."""
    with pytest.raises(ValidationError):
        _declare([{"type": "supply"}])


def test_a_supply_aimed_at_a_region_cannot_be_expressed():
    """The model reached for `region` because every other action has one."""
    with pytest.raises(ValidationError):
        _declare([{"type": "supply", "region": "capital"}])


def test_a_supply_names_an_actor_and_only_an_actor():
    declaration = _declare([{"type": "supply", "target_actor": "DEF"}])
    actions = to_actions(declaration, "ATK")
    assert actions[0].target_actor == "DEF"
    assert actions[0].region is None


def test_an_actor_cannot_supply_itself():
    with pytest.raises(ValidationError):
        _declare([{"type": "supply", "target_actor": "ATK"}])


def test_a_region_that_is_not_on_the_map_cannot_be_expressed():
    """`unknown region 'cu-air-defense'` — the model put a force identifier where
    a region goes."""
    with pytest.raises(ValidationError):
        _declare([{"type": "strike", "region": "atk-air-defense"}])


def test_an_invented_region_for_a_statement_cannot_be_expressed():
    """Both models kept inventing 'global' and 'international'. A statement has
    no region at all now, so there is nowhere to put one."""
    with pytest.raises(ValidationError):
        _declare([{"type": "statement", "region": "global"}])


def test_an_action_type_that_was_not_offered_cannot_be_expressed():
    with pytest.raises(ValidationError):
        _declare([{"type": "invade", "region": "capital"}], legal=("hold", "statement"))


def test_an_intensity_outside_the_range_cannot_be_expressed():
    with pytest.raises(ValidationError):
        _declare([{"type": "strike", "region": "capital", "intensity": 1000}])


def test_more_than_the_maximum_actions_cannot_be_expressed():
    with pytest.raises(ValidationError):
        _declare([{"type": "hold"}] * (MAX_ACTIONS_PER_TURN + 1))


def test_an_empty_declaration_cannot_be_expressed():
    with pytest.raises(ValidationError):
        _declare([])


# --- what should still work -------------------------------------------------


def test_a_well_formed_declaration_converts_to_engine_actions():
    declaration = _declare(
        [
            {"type": "strike", "region": "capital", "intensity": 2},
            {"type": "hold"},
        ]
    )
    actions = to_actions(declaration, "ATK")
    assert [a.type for a in actions] == ["strike", "hold"]
    assert actions[0].region == "capital" and actions[0].intensity == 2
    assert all(a.actor == "ATK" for a in actions)


def test_intensity_defaults_to_one_when_omitted():
    actions = to_actions(_declare([{"type": "strike", "region": "capital"}]), "ATK")
    assert actions[0].intensity == 1


def test_deploy_carries_force_identifiers():
    declaration = _declare(
        [{"type": "deploy", "region": "capital", "forces": ["atk-marines"]}],
        legal=("deploy",),
    )
    assert to_actions(declaration, "ATK")[0].forces == ("atk-marines",)


def test_every_legal_type_can_be_declared_with_its_own_fields():
    """A type in the vocabulary that cannot actually be spoken is worse than one
    that is missing, because it fails silently at the far end."""
    for action_type in sorted(ACTION_TYPES):
        payload: dict = {"type": action_type}
        if "region" in FIELDS[action_type]:
            payload["region"] = "capital"
        if "target" in FIELDS[action_type]:
            payload["target_actor"] = "DEF"
        declaration = _declare([payload], legal=(action_type,))
        assert to_actions(declaration, "ATK")[0].type == action_type


# --- the two tables must not drift ------------------------------------------


def test_the_vocabulary_matches_the_engine():
    assert vocabulary_matches_the_engine(), (
        set(FIELDS) ^ set(ACTION_TYPES),
        set(FIELDS) ^ set(DESCRIPTIONS),
    )


def test_every_action_the_resolver_can_reject_for_reach_declares_a_region():
    """If the resolver checks reach for an action type, that type has to carry a
    region, or the check is unreachable."""
    for action_type in rules.DELIVERY_KINDS:
        assert "region" in FIELDS[action_type], action_type


def test_supply_is_the_only_action_that_names_an_actor_and_no_region():
    targeted = {t for t, f in FIELDS.items() if "target" in f}
    assert "supply" in targeted
    for action_type in targeted:
        assert "region" not in FIELDS[action_type], f"{action_type} has both"


# --- the schema handed to the provider --------------------------------------


def test_the_schema_enumerates_the_regions_rather_than_asking_for_a_string():
    """This is the whole mechanism: the provider enforces the enum server-side,
    so an invalid region never reaches us."""
    schema = _model(legal=("strike",)).model_json_schema()
    strike = next(iter(schema["$defs"].values()))
    assert strike["properties"]["region"]["enum"] == list(REGIONS)


def test_the_schema_carries_the_description_of_each_action():
    schema = _model(legal=("supply",)).model_json_schema()
    supply = next(iter(schema["$defs"].values()))
    assert supply["description"] == DESCRIPTIONS["supply"]


def test_building_a_model_with_no_legal_actions_is_an_error_not_an_empty_union():
    with pytest.raises(ValueError, match="no legal actions"):
        declaration_model("ATK", (), REGIONS, ACTORS)


def test_the_model_is_cached_so_a_turn_does_not_rebuild_it():
    first = _model()
    second = _model()
    assert first is second
