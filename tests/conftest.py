"""Shared fixtures. The builders live in `helpers.py` so test modules can
import them directly.
"""

from __future__ import annotations

import pytest
from v1shape import WorldState

from helpers import make_force, make_world


@pytest.fixture
def world() -> WorldState:
    return make_world(
        forces=(
            make_force("DEF", "ground", region="r1", strength=50.0),
            make_force("ATK", "naval", region="sea-1", strength=80.0),
        )
    )
