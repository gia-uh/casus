"""The decorators and the registry."""

import types

import pytest

from casus.ruleset import PHASES, RuleSet, offer, rule, view


def _module_with(names, phase):
    module = types.ModuleType("scenario_rules")
    for name in names:

        def fn(s, _name=name):
            pass

        fn.__name__ = name
        setattr(module, name, rule(phase=phase)(fn))
    return module


def test_the_five_phases_in_their_fixed_order():
    assert PHASES == ("legality", "upkeep", "movement", "contest", "consequences")


def test_rules_run_in_declaration_order_within_a_phase():
    module = _module_with(["b", "a", "c"], phase="contest")
    assert [r.name for r in RuleSet.from_module(module).for_phase("contest")] == ["b", "a", "c"]


def test_an_unknown_phase_is_refused_at_decoration_not_at_run_time():
    with pytest.raises(ValueError, match="unknown phase 'combat'"):

        @rule(phase="combat")
        def whatever(s):
            pass


def test_a_rule_remembers_the_action_type_it_runs_on():
    module = types.ModuleType("m")

    @rule(phase="contest", on="strike")
    def bombing(s, a):
        pass

    module.bombing = bombing
    (only,) = RuleSet.from_module(module).for_phase("contest")
    assert (only.name, only.on) == ("bombing", ("strike",))


def test_hooks_are_found_and_absent_hooks_are_none():
    module = types.ModuleType("m")

    @offer
    def what_can_i_do(s, actor):
        return {}

    module.what_can_i_do = what_can_i_do
    rules = RuleSet.from_module(module)
    assert rules.offer is what_can_i_do
    assert rules.view is None


def test_two_offer_hooks_are_refused_naming_both():
    module = types.ModuleType("m")

    @offer
    def first(s, actor):
        return {}

    @offer
    def second(s, actor):
        return {}

    module.first, module.second = first, second
    with pytest.raises(ValueError, match="first.*second"):
        RuleSet.from_module(module)


def test_a_view_hook_is_registered():
    module = types.ModuleType("m")

    @view
    def fog(s, actor):
        pass

    module.fog = fog
    assert RuleSet.from_module(module).view is fog


def test_a_rule_may_run_on_several_action_types():
    """v1's legality check is one function over every action type, and reject()
    needs the action it rejects, so one rule has to cover several types."""
    module = types.ModuleType("m")

    @rule(phase="legality", on=("strike", "invade"))
    def needs_platforms(s, a):
        pass

    module.needs_platforms = needs_platforms
    (only,) = RuleSet.from_module(module).for_phase("legality")
    assert only.on == ("strike", "invade")
