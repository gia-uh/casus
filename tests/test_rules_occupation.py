import random

from casus.v1 import rules
from casus.v1.state import Action
from helpers import make_actor, make_force, make_region, make_world

#: Populations used below. Ten million and 2.1 million are the orders of magnitude the
#: stability-operations literature is calibrated against, which is why they are
#: the numbers here.
LARGE_POPULATION = 10_000_000
CITY_POPULATION = 2_100_000


def test_occupation_requirement_is_one_per_fifty_inhabitants():
    assert rules.occupation_requirement(LARGE_POPULATION) == 200_000
    assert rules.occupation_requirement(CITY_POPULATION) == 42_000
    assert rules.INHABITANTS_PER_SECURITY_MEMBER == 50


def test_the_published_external_figure_falls_out_of_the_rule():
    """The published estimate for a ten-million population is about 100,000
    external troops, assuming half the
    total comes from indigenous police. The rule returns the total, so the
    published number is the total halved, and this assertion keeps the two
    consistent."""
    total = rules.occupation_requirement(LARGE_POPULATION)
    assert total // 2 == 100_000


def test_control_decays_when_the_occupier_is_below_the_ratio():
    world = make_world(
        regions={
            "capital": make_region(
                "capital",
                owner="ATK",
                country="DEF",
                control=90.0,
                population=CITY_POPULATION,
                terrain="urban",
            )
        },
        forces=(make_force("ATK", "ground", region="capital", strength=20.0),),
    )
    out, resolutions = rules.resolve(
        world, [Action(actor="ATK", type="hold")], random.Random(2)
    )

    assert out.regions["capital"].control < 90.0
    short = next(r for r in resolutions if r.kind == "insufficient_occupation_force")
    assert short.detail["required"] == 42_000
    assert short.detail["present"] == 20 * rules.TROOPS_PER_STRENGTH_POINT


def test_control_holds_when_the_occupier_meets_the_ratio():
    enough = rules.occupation_requirement(CITY_POPULATION) / rules.TROOPS_PER_STRENGTH_POINT
    world = make_world(
        regions={
            "capital": make_region(
                "capital",
                owner="ATK",
                country="DEF",
                control=90.0,
                population=CITY_POPULATION,
                terrain="urban",
            )
        },
        forces=(make_force("ATK", "ground", region="capital", strength=enough + 1),),
    )
    out, resolutions = rules.resolve(
        world, [Action(actor="ATK", type="hold")], random.Random(2)
    )
    assert out.regions["capital"].control == 90.0
    assert not [r for r in resolutions if r.kind == "insufficient_occupation_force"]


def test_a_bigger_shortfall_decays_control_faster():
    def control_after(strength):
        world = make_world(
            regions={
                "capital": make_region(
                    "capital",
                    owner="ATK",
                    country="DEF",
                    control=90.0,
                    population=CITY_POPULATION,
                    terrain="urban",
                )
            },
            forces=(make_force("ATK", "ground", region="capital", strength=strength),),
        )
        out, _ = rules.resolve(world, [Action(actor="ATK", type="hold")], random.Random(2))
        return out.regions["capital"].control

    assert control_after(1.0) < control_after(40.0)


def test_a_region_held_by_its_own_country_is_not_an_occupation():
    world = make_world(
        regions={
            "capital": make_region(
                "capital",
                owner="DEF",
                country="DEF",
                control=90.0,
                population=CITY_POPULATION,
            )
        },
        forces=(),
    )
    out, resolutions = rules.resolve(
        world, [Action(actor="DEF", type="hold")], random.Random(1)
    )
    assert out.regions["capital"].control == 90.0
    assert not [r for r in resolutions if r.kind == "insufficient_occupation_force"]


def test_an_insurgency_forms_in_an_under_occupied_region():
    world = make_world(
        regions={
            "capital": make_region(
                "capital",
                owner="ATK",
                country="DEF",
                control=90.0,
                population=CITY_POPULATION,
                terrain="urban",
            )
        },
        forces=(make_force("ATK", "ground", region="capital", strength=5.0),),
    )
    out, resolutions = rules.resolve(
        world, [Action(actor="ATK", type="hold")], random.Random(1)
    )

    assert any(r.kind == "insurgency_formed" for r in resolutions)
    insurgents = [f for f in out.forces if f.owner == "DEF" and f.kind == "irregular"]
    assert len(insurgents) == 1
    assert insurgents[0].strength == rules.INSURGENT_REGENERATION


def test_an_existing_insurgency_grows_rather_than_duplicating():
    state = make_world(
        regions={
            "capital": make_region(
                "capital",
                owner="ATK",
                country="DEF",
                control=90.0,
                population=CITY_POPULATION,
                terrain="urban",
            )
        },
        forces=(make_force("ATK", "ground", region="capital", strength=5.0),),
    )
    for _ in range(3):
        state, _ = rules.resolve(state, [Action(actor="ATK", type="hold")], random.Random(1))

    insurgents = [f for f in state.forces if f.owner == "DEF" and f.kind == "irregular"]
    assert len(insurgents) == 1, "one insurgency, not one per turn"
    assert insurgents[0].strength > rules.INSURGENT_REGENERATION


def test_control_never_goes_below_zero():
    state = make_world(
        actors={"ATK": make_actor("ATK", fuel_days=5000.0), "DEF": make_actor("DEF")},
        regions={
            "capital": make_region(
                "capital",
                owner="ATK",
                country="DEF",
                control=5.0,
                population=CITY_POPULATION,
                terrain="urban",
            )
        },
        forces=(make_force("ATK", "ground", region="capital", strength=1.0),),
    )
    for _ in range(6):
        state, _ = rules.resolve(state, [Action(actor="ATK", type="hold")], random.Random(1))
    assert state.regions["capital"].control == 0.0
