import random

from casus import rules
from casus.state import Action
from helpers import make_actor, make_force, make_region, make_world


def _campaign_world(ad_strength=60.0, us_fuel=5000.0):
    """US fuel is deliberately abundant. The calibration below measures the
    suppression rule alone; with realistic fuel the campaign drops to garrison
    mid-way and the curve mixes two rules together, which is a finding in its own
    right and is tested separately."""
    return make_world(
        actors={
            "ATK": make_actor("ATK", fuel_days=us_fuel, fuel_inflow=us_fuel / 10),
            "DEF": make_actor("DEF"),
        },
        regions={
            "target": make_region("target", "DEF", terrain="urban", adjacency=("sea-1",)),
            "sea-1": make_region(
                "sea-1", "", terrain="sea", population=0, adjacency=("target",)
            ),
        },
        forces=(
            make_force("ATK", "air", region="sea-1", strength=100.0, readiness=0.9),
            make_force(
                "DEF", "air_defense", region="target", strength=ad_strength, readiness=0.5
            ),
        ),
    )


def _ad_strength(state):
    return sum(f.strength for f in state.forces if f.kind == "air_defense")


def test_sustained_strikes_suppress_air_defence_in_four_to_five_turns():
    """The calibration target, stated in the constant's comment: a 60-point
    battery under a sustained intensity-3 campaign by a 100-point air force."""
    state = _campaign_world()
    turns = 0
    for _ in range(10):
        state, resolutions = rules.resolve(
            state,
            [Action(actor="ATK", type="air_campaign", region="target", intensity=3)],
            random.Random(11),
        )
        turns += 1
        if any(r.kind == "air_defence_suppressed" for r in resolutions):
            break
    assert 4 <= turns <= 5, f"suppression took {turns} turns"


def test_suppression_is_reported_with_the_before_and_after_strength():
    state = _campaign_world()
    _, resolutions = rules.resolve(
        state,
        [Action(actor="ATK", type="air_campaign", region="target", intensity=2)],
        random.Random(1),
    )
    degraded = next(r for r in resolutions if r.kind == "air_defence_degraded")
    assert degraded.detail["before"] > degraded.detail["after"]
    assert degraded.region == "target"


def test_a_lower_intensity_campaign_takes_longer():
    def turns_to_suppress(intensity):
        state = _campaign_world()
        for turn in range(1, 21):
            state, resolutions = rules.resolve(
                state,
                [
                    Action(
                        actor="ATK", type="air_campaign", region="target", intensity=intensity
                    )
                ],
                random.Random(11),
            )
            if any(r.kind == "air_defence_suppressed" for r in resolutions):
                return turn
        return 99

    assert turns_to_suppress(1) > turns_to_suppress(3)


def test_the_suppressed_event_fires_exactly_once():
    state = _campaign_world()
    fired = 0
    for _ in range(8):
        state, resolutions = rules.resolve(
            state,
            [Action(actor="ATK", type="air_campaign", region="target", intensity=3)],
            random.Random(11),
        )
        fired += sum(1 for r in resolutions if r.kind == "air_defence_suppressed")
    assert fired == 1


def test_air_defence_is_not_ground_down_by_the_lanchester_exchange():
    """Before this rule a 60-point battery evaporated in one turn, which
    contradicts every published account of a suppression campaign."""
    state = _campaign_world()
    after, _ = rules.resolve(
        state,
        [Action(actor="ATK", type="air_campaign", region="target", intensity=3)],
        random.Random(11),
    )
    lost = _ad_strength(state) - _ad_strength(after)
    assert 0 < lost < 20, f"lost {lost:.1f} in one turn"


def test_surviving_air_defence_blunts_the_strike_on_other_forces():
    def army_loss(ad_strength):
        world = make_world(
            regions={
                "target": make_region("target", "DEF", terrain="urban", adjacency=("sea-1",)),
                "sea-1": make_region(
                    "sea-1", "", terrain="sea", population=0, adjacency=("target",)
                ),
            },
            forces=(
                make_force("ATK", "air", region="sea-1", strength=100.0),
                make_force("DEF", "ground", region="target", strength=50.0),
                make_force(
                    "DEF",
                    "air_defense",
                    region="target",
                    strength=ad_strength,
                    id="DEF-air_defense-1",
                ),
            ),
        )
        out, _ = rules.resolve(
            world,
            [Action(actor="ATK", type="air_campaign", region="target", intensity=2)],
            random.Random(4),
        )
        army = next(f for f in out.forces if f.kind == "ground")
        return 50.0 - army.strength

    assert army_loss(60.0) < army_loss(0.0), "air defence should reduce incoming damage"


def test_an_already_suppressed_defence_imposes_no_penalty():
    below_floor = rules.SUPPRESSION_FLOOR - 1.0
    assert rules._air_defence_divisor([]) == 1.0
    from helpers import make_force as mf

    assert rules._air_defence_divisor([mf("DEF", "air_defense", strength=below_floor)]) == 1.0
    assert rules._air_defence_divisor([mf("DEF", "air_defense", strength=60.0)]) > 1.0


def test_running_out_of_fuel_lengthens_a_suppression_campaign():
    """The campaign drops to garrison posture when the fuel runs out, which
    lowers its air power and stretches the suppression timeline. Two rules
    interacting, and the interaction is the interesting part."""

    def turns_to_suppress(us_fuel):
        # A tougher battery, so the gap is wide enough to cross a turn boundary:
        # at 60 points both cases still suppress on turn 4 and the effect hides.
        state = _campaign_world(ad_strength=90.0, us_fuel=us_fuel)
        for turn in range(1, 21):
            state, resolutions = rules.resolve(
                state,
                [Action(actor="ATK", type="air_campaign", region="target", intensity=3)],
                random.Random(11),
            )
            if any(r.kind == "air_defence_suppressed" for r in resolutions):
                return turn
        return 99

    assert turns_to_suppress(us_fuel=60.0) > turns_to_suppress(us_fuel=5000.0)
