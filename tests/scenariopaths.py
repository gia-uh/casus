"""Where the tests look for scenarios.

The shipped `smoke.yaml` is always present and carries every validation test.
Scenarios built for a class live outside the repo and reach it through the
gitignored `scenarios/private` link; the tests that check their provenance run
when that link resolves and skip when it does not.

The skip is deliberate rather than a convenience. A scenario whose figures have
no sources should fail the suite of whoever maintains it, even though the
scenario never ships with the engine.
"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).parent.parent
SCENARIOS = ROOT / "scenarios"
SMOKE = SCENARIOS / "smoke.yaml"

PRIVATE = SCENARIOS / "private"
PRIVATE_SOURCES = PRIVATE / "SOURCES.md"

#: Every private scenario found, so provenance is checked across all of them
#: rather than against one name this repo is not supposed to know.
PRIVATE_SCENARIOS = sorted(PRIVATE.glob("*.yaml")) if PRIVATE.is_dir() else []

requires_private = pytest.mark.skipif(
    not PRIVATE_SCENARIOS,
    reason="no scenarios/private link; class scenarios are not published",
)


def all_scenarios() -> list[pathlib.Path]:
    return [SMOKE, *PRIVATE_SCENARIOS]


#: v2 scenarios are directories holding a scenario.yaml, shipped or private.
PRIVATE_DIRS = (
    sorted(p.parent for p in PRIVATE.glob("*/scenario.yaml")) if PRIVATE.is_dir() else []
)
requires_private_dirs = pytest.mark.skipif(
    not PRIVATE_DIRS, reason="no scenarios/private link; class scenarios are not published"
)


def scenario_dirs() -> list[pathlib.Path]:
    shipped = sorted(p.parent for p in SCENARIOS.glob("*/scenario.yaml"))
    return [*shipped, *PRIVATE_DIRS]
