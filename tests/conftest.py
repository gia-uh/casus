"""Shared fixtures. The builders live in `helpers.py` so test modules can
import them directly.
"""

from __future__ import annotations

import pytest

from casus.state import WorldState
from helpers import make_force, make_world


@pytest.fixture
def world() -> WorldState:
    return make_world(
        forces=(
            make_force("CU", "ground", region="r1", strength=50.0),
            make_force("US", "naval", region="sea-1", strength=80.0),
        )
    )
