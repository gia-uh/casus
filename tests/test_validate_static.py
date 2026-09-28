"""The static validator: what a rules file may not do, found without running it."""

import pathlib
import textwrap

import pytest

from casus.validate.static import check_source

ROOT = pathlib.Path(__file__).parent.parent


def _source(text: str) -> str:
    return textwrap.dedent(text)


def _codes(text: str) -> list[str]:
    return [f.code for f in check_source(_source(text))]


def test_assigning_to_state_directly_is_rejected_with_a_line():
    findings = check_source(
        _source("""
        @rule(phase="contest")
        def sneaky(s):
            s.place("capital").infra = 5
    """)
    )
    assert [f.code for f in findings] == ["direct-assignment"]
    assert findings[0].line == 4
    assert "s.add" in findings[0].message, "a rejection has to say what to do instead"


def test_an_augmented_assignment_to_state_is_rejected_too():
    assert _codes("""
        @rule(phase="contest")
        def sneaky(s):
            s.place("capital").infra += 5
    """) == ["direct-assignment"]


def test_an_import_outside_the_whitelist_is_rejected():
    assert _codes("import os\n") == ["forbidden-import"]
    assert _codes("from subprocess import run\n") == ["forbidden-import"]


def test_importing_random_names_the_seeded_generator():
    (finding,) = check_source("import random\n")
    assert finding.code == "forbidden-import"
    assert "s.rng" in finding.message


@pytest.mark.parametrize("call", ["eval('1')", "open('x')", "__import__('os')", "exec('')",
                                  "id(s)", "hash(s)", "setattr(s, 'x', 1)"])  # fmt: skip
def test_a_forbidden_call_is_rejected(call):
    assert _codes(f"""
        @rule(phase="contest")
        def r(s):
            {call}
    """) == ["forbidden-call"]


def test_dunder_access_is_rejected():
    assert _codes("""
        @rule(phase="contest")
        def r(s):
            return s.__class__
    """) == ["forbidden-call"]


def test_writing_module_state_from_a_rule_is_rejected():
    assert _codes("""
        SEEN = []

        @rule(phase="contest")
        def remembers(s):
            SEEN.append(1)
    """) == ["module-state"]
    assert _codes("""
        COUNT = 0

        @rule(phase="contest")
        def counts(s):
            global COUNT
            COUNT = COUNT + 1
    """) == ["module-state"]


def test_an_unknown_phase_is_found_without_running_the_file():
    assert _codes("""
        @rule(phase="combat")
        def r(s):
            pass
    """) == ["unknown-phase"]


def test_a_rule_signature_that_does_not_match_its_decorator_is_rejected():
    assert _codes("""
        @rule(phase="contest", on="strike")
        def r(s):
            pass
    """) == ["bad-signature"]
    assert _codes("""
        @offer
        def o(s):
            return {}
    """) == ["bad-signature"]


def test_every_finding_is_reported_not_just_the_first():
    assert sorted(
        _codes("""
        import os

        @rule(phase="contest")
        def sneaky(s):
            s.place("capital").infra = 5
    """)
    ) == ["direct-assignment", "forbidden-import"]


def test_ordinary_local_arithmetic_is_not_flagged():
    """A validator that rejects correct rules is worse than none: the author
    stops reading it."""
    assert (
        check_source(
            _source("""
        @rule(phase="contest", on="strike")
        def fine(s, a):
            damage = 8 * a.intensity
            for p in s.places:
                s.add(p.infra, -damage)
    """)
        )
        == []
    )


def test_local_containers_may_be_built_and_changed():
    assert (
        _codes("""
        TABLE = {"a": 1}

        @rule(phase="contest")
        def fine(s):
            seen = []
            seen.append(TABLE["a"])
            totals = {}
            totals["x"] = sum(seen)
    """)
        == []
    )


@pytest.mark.parametrize("scenario", ["smoke", "reference"])
def test_the_shipped_rulesets_are_clean(scenario):
    path = ROOT / "scenarios" / scenario / "rules.py"
    assert check_source(path.read_text(), str(path)) == []


def test_a_finding_names_its_file():
    (finding,) = check_source("import os\n", "scenarios/x/rules.py")
    assert finding.file == "scenarios/x/rules.py"
