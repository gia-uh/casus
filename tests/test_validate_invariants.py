"""Scenario invariants: the 2026-09-27 ratchet, as a gate."""

import textwrap

import pytest
import yaml
from scenariopaths import SCENARIOS

from casus.scenario import Scenario
from casus.validate.invariants import check_invariants


def _scenario_with(rules, resources=None, attributes=None, support=30.0, distress=40.0):
    resources = resources or {"support": {"min": 0, "max": 100}}
    attributes = attributes or {"distress": {"min": 0, "max": 100}}
    data = {
        "name": "invariants",
        "resources": resources,
        "attributes": attributes,
        "actions": {
            "hold": {"fields": []},
            "strike": {"fields": ["place", "intensity"], "intensity": [1, 3]},
        },
        "actors": {
            a: {"name": a, "model": "m", "briefing": "b", "resources": {"support": support}}
            for a in ("ATK", "DEF")
        },
        "places": {
            p: {"name": p, "owner": "DEF", "attrs": {"distress": distress}}
            for p in ("north", "south")
        },
    }
    source = "from casus.ruleset import rule\n\n" + textwrap.dedent(rules)
    return Scenario.from_parts(data, source)


def test_a_quantity_that_can_only_fall_is_rejected():
    """On 2026-09-27 Cuban domestic support reached zero on turn six with every
    actor holding, and survived 196 tests, two scored runs and a careful reading
    of the results. This is that defect, as a gate."""
    findings = check_invariants(_scenario_with(
        resources={"support": {"min": 0, "max": 100, "monotone": False}},
        rules='''
            @rule(phase="consequences")
            def drain(s):
                for a in s.actors:
                    s.add(a.support, -4)
        '''))  # fmt: skip
    assert {f.code for f in findings} == {"monotone-quantity", "pinned-at-bound"}
    assert all("support" in f.message for f in findings)
    assert "never rose" in next(f for f in findings if f.code == "monotone-quantity").message


def test_a_quantity_that_eases_while_everyone_holds_is_not_flagged():
    """Distress falling while nobody attacks is one-directional under holding
    and entirely correct. A check that rejects it is the check the author
    learns to ignore."""
    findings = check_invariants(_scenario_with(
        attributes={"distress": {"min": 0, "max": 100, "monotone": False}},
        rules='''
            @rule(phase="contest", on="strike")
            def harm(s, a):
                s.add(s.place(a.place).distress, 10 * a.intensity)
                s.emit("attacked", place=a.place)

            @rule(phase="consequences")
            def ease(s):
                for p in s.places:
                    if not s.happened("attacked", place=p.id):
                        s.decay(p.distress, toward=0, rate=0.1)
        '''))  # fmt: skip
    assert findings == []


def test_a_quantity_that_never_moves_is_flagged_too():
    """Otherwise a declared two-way quantity passes by never moving at all."""
    findings = check_invariants(_scenario_with(
        resources={"support": {"min": 0, "max": 100, "monotone": False}},
        rules='''
            @rule(phase="upkeep")
            def nothing(s):
                pass
        '''))  # fmt: skip
    (finding,) = findings
    assert finding.code == "monotone-quantity"
    assert "never rose" in finding.message and "never fell" in finding.message


def test_a_recovery_that_cannot_fire_still_leaves_the_quantity_pinned():
    findings = check_invariants(_scenario_with(
        resources={"support": {"min": 0, "max": 100, "monotone": False}},
        rules='''
            @rule(phase="consequences")
            def drain(s):
                for a in s.actors:
                    s.add(a.support, -4)

            @rule(phase="consequences")
            def recover_when_strong(s):
                for a in s.actors:
                    if a.support > 90:
                        s.add(a.support, 1)
        '''))  # fmt: skip
    assert "pinned-at-bound" in {f.code for f in findings}


def test_a_quantity_that_starts_at_its_bound_is_not_pinned():
    """Distress at zero in a place nobody touches has not been driven anywhere."""
    findings = check_invariants(_scenario_with(
        attributes={"distress": {"min": 0, "max": 100, "monotone": False}},
        distress=0.0,
        rules='''
            @rule(phase="contest", on="strike")
            def harm(s, a):
                s.add(s.place(a.place).distress, 10)
                s.emit("attacked", place=a.place)

            @rule(phase="consequences")
            def ease(s):
                for p in s.places:
                    if not s.happened("attacked", place=p.id):
                        s.decay(p.distress, toward=0, rate=0.5)
        '''))  # fmt: skip
    assert "pinned-at-bound" not in {f.code for f in findings}


@pytest.mark.parametrize("name", ["smoke", "reference"])
def test_the_shipped_scenarios_hold_their_invariants(name):
    assert check_invariants(Scenario.load(SCENARIOS / name)) == []


def test_a_quantity_that_eases_linearly_to_its_floor_is_not_pinned():
    """Final review: `s.add(p.distress, -5)` reaches zero exactly, where decay
    never does. Reaching the floor while everyone holds is correct when
    something can raise it again."""
    findings = check_invariants(_scenario_with(
        attributes={"distress": {"min": 0, "max": 100, "monotone": False}},
        rules='''
            @rule(phase="contest", on="strike")
            def harm(s, a):
                s.add(s.place(a.place).distress, 10 * a.intensity)
                s.emit("attacked", place=a.place)

            @rule(phase="consequences")
            def ease(s):
                for p in s.places:
                    if not s.happened("attacked", place=p.id):
                        s.add(p.distress, -5)
        '''))  # fmt: skip
    assert findings == []


def test_the_gate_rejects_the_reference_physics_when_the_ratchet_is_declared():
    """The evidence the spec cares about, in CI: the reference ruleset as ported
    from v1 cannot raise domestic support or lower distress."""
    reference = Scenario.load(SCENARIOS / "reference")
    data = yaml.safe_load(yaml.safe_dump(reference.data))
    data["resources"]["domestic_support"]["monotone"] = False
    data["attributes"]["civilian_distress"]["monotone"] = False
    findings = check_invariants(Scenario.from_parts(data, reference.rules_source))
    monotone = {f.message.split("'")[1] for f in findings if f.code == "monotone-quantity"}
    assert monotone == {"domestic_support", "civilian_distress"}
