"""The engine's core performs no I/O and talks to no model. The design rests on
it, so the claim gets a test rather than a sentence."""

import pathlib

import pytest

from casus import proxy, resolver, ruleset, state

FORBIDDEN = (
    "httpx",
    "lingo",
    "import requests",
    "open(",
    "pathlib",
    "subprocess",
    "urllib",
    "import os",
    "import time",
    "datetime",
)


@pytest.mark.parametrize("module", [state, proxy, ruleset, resolver], ids=lambda m: m.__name__)
def test_the_core_module_performs_no_io(module):
    source = pathlib.Path(module.__file__).read_text()
    for forbidden in FORBIDDEN:
        assert forbidden not in source, f"{module.__name__} must stay pure: found {forbidden!r}"
