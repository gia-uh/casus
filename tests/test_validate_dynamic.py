"""The dynamic validator: one dry turn, run for real, with everyone holding."""

import textwrap

import pytest
from scenariopaths import SCENARIOS

from casus.scenario import Scenario
from casus.validate.dynamic import dry_run

SMOKE = Scenario.load(SCENARIOS / "smoke")

#: Eight places, so an order that depends on string hashing differs between two
#: hash seeds with near certainty rather than by luck.
PLACES = {
    f"zone-{c}": {"name": c, "owner": "BLUE", "attrs": {"infra": 100}} for c in "abcdefgh"
}


def _scenario_with_rule(source: str, places=None) -> Scenario:
    data = dict(SMOKE.data)
    if places:
        data = {**data, "places": places, "entities": []}
    rules = "from casus.ruleset import rule\n\n" + textwrap.dedent(source)
    return Scenario.from_parts(data, rules)


def _scenario_whose_rule_touches(place: str) -> Scenario:
    return _scenario_with_rule(f"""
        @rule(phase="consequences")
        def looks_for_it(s):
            s.add(s.place({place!r}).infra, -1)
    """)


def test_a_rule_naming_a_place_that_does_not_exist_is_caught_by_the_dry_run():
    findings = dry_run(_scenario_whose_rule_touches("atlantis")).findings
    assert findings[0].code == "unknown-place"
    assert "atlantis" in findings[0].message
    assert "looks_for_it" in findings[0].message


def test_a_rule_naming_an_undeclared_resource_is_caught():
    findings = dry_run(
        _scenario_with_rule("""
        @rule(phase="upkeep")
        def tired(s):
            for a in s.actors:
                s.add(a.morale, -1)
    """)
    ).findings
    assert [f.code for f in findings] == ["unknown-resource"]
    assert "morale" in findings[0].message


def test_a_rule_on_an_undeclared_action_is_caught():
    findings = dry_run(
        _scenario_with_rule("""
        @rule(phase="contest", on="teleport")
        def arrive(s, a):
            pass
    """)
    ).findings
    assert [f.code for f in findings] == ["unknown-action"]
    assert "teleport" in findings[0].message


def test_the_dry_run_catches_order_that_depends_on_string_hashing():
    """Within one process set order is stable, so running twice in-process
    proves nothing. Two processes with different hash seeds disagree."""
    findings = dry_run(
        _scenario_with_rule(
            """
        @rule(phase="contest")
        def wobbly(s):
            for i, ident in enumerate({p.id for p in s.places}):
                s.add(s.place(ident).infra, -i)
    """,
            places=PLACES,
        )
    ).findings
    assert [f.code for f in findings] == ["nondeterministic"]


def test_sorting_makes_the_same_rule_deterministic():
    findings = dry_run(
        _scenario_with_rule(
            """
        @rule(phase="contest")
        def steady(s):
            for i, ident in enumerate(sorted({p.id for p in s.places})):
                s.add(s.place(ident).infra, -i)
    """,
            places=PLACES,
        )
    ).findings
    assert findings == []


def test_a_rule_that_writes_module_state_is_caught_at_run_time_too():
    """The static check catches the obvious forms; this catches what it cannot
    see, such as a mutation through an alias."""
    findings = dry_run(
        _scenario_with_rule("""
        SEEN = []
        ALIAS = SEEN

        @rule(phase="contest")
        def remembers(s):
            keep = ALIAS
            keep.append(1)
    """)
    ).findings
    assert [f.code for f in findings] == ["module-state"]
    assert "SEEN" in findings[0].message or "ALIAS" in findings[0].message


def test_the_report_carries_the_trajectory_and_the_ledger():
    report = dry_run(SMOKE, turns=2)
    # two holding turns, then one cover turn per declared action type
    assert len(report.trajectory) == 1 + 2 + len(SMOKE.actions)
    assert report.findings == []
    assert any(m.rule == "upkeep" for m in report.ledger)


@pytest.mark.parametrize("name", ["smoke", "reference"])
def test_the_shipped_scenarios_pass_the_dry_run(name):
    assert dry_run(Scenario.load(SCENARIOS / name), turns=2).findings == []


def test_the_cross_process_check_runs_once_per_scenario_content(monkeypatch):
    """Its result depends only on the data and the rules, and it costs two
    interpreter starts, so loading the same scenario twice pays once."""
    from casus.validate import dynamic

    scenario = _scenario_with_rule("""
        @rule(phase="upkeep")
        def unique_to_this_test(s):
            pass
    """)
    calls = []
    real = dynamic.subprocess.Popen
    monkeypatch.setattr(
        dynamic.subprocess, "Popen", lambda *a, **k: calls.append(1) or real(*a, **k)
    )
    dry_run(scenario)
    dry_run(scenario)
    assert len(calls) == len(dynamic.HASH_SEEDS)


# --- final review: what the dry run must reach beyond holding turns ---------


def test_a_rule_on_an_action_is_exercised_by_the_dry_run():
    findings = dry_run(
        _scenario_with_rule("""
        @rule(phase="contest", on="raid")
        def lost(s, a):
            s.place("atlantis")
    """)
    ).findings
    assert [f.code for f in findings] == ["unknown-place"]


def test_a_nondeterministic_rule_on_an_action_is_caught():
    findings = dry_run(
        _scenario_with_rule(
            """
        @rule(phase="contest", on="deploy")
        def wobbly(s, a):
            for i, ident in enumerate({p.id for p in s.places}):
                s.add(s.place(ident).infra, -i)
    """,
            places=PLACES,
        )
    ).findings
    assert "nondeterministic" in [f.code for f in findings]


def test_the_view_and_offer_hooks_run_in_the_dry_run():
    source = SMOKE.rules_source.replace("@view\ndef fog", "def fog") + textwrap.dedent("""

        @view
        def peek(s, actor):
            s.actor(actor).morale
    """)
    findings = dry_run(Scenario.from_parts(SMOKE.data, source)).findings
    assert "unknown-resource" in [f.code for f in findings]


def test_a_path_that_skips_the_proxy_is_caught_by_replaying_the_ledger():
    """The static check forbids the known ways; this catches the rest by
    comparing the world with what the ledger says happened."""
    import types

    from casus.ruleset import RuleSet, rule

    module = types.ModuleType("sneaky")

    @rule(phase="consequences")
    def sneaky(s):
        s._places["border"]["attrs"]["infra"] = 5.0

    module.sneaky = sneaky
    scenario = Scenario(data=SMOKE.data, rules_source="", ruleset=RuleSet.from_module(module),
                        origin="sneaky", module=module)  # fmt: skip
    findings = dry_run(scenario).findings
    assert "ledger-mismatch" in [f.code for f in findings]
    assert "place.border.infra" in next(
        f.message for f in findings if f.code == "ledger-mismatch"
    )


def test_a_print_in_a_rule_does_not_break_the_cross_process_check():
    assert (
        dry_run(
            _scenario_with_rule("""
        @rule(phase="consequences")
        def chatty(s):
            print("infra now", [p.infra for p in s.places])
    """)
        ).findings
        == []
    )
