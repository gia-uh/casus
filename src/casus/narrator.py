"""Turn narration. Reads the resolved world, writes prose, changes nothing.

The narrator exists because a table of resolution records is unreadable to
anyone who did not write it, and the audience for this harness is not engineers.

It is a separate module for one reason: `test_narrator_cannot_mutate_state`. The
moment a model is allowed to adjust a number for narrative reasons, every figure
in the run stops being auditable.

The dispatch is a typed object rather than free text, and each line's `actor` is
an enum over the actors in play. In the first Caribbean run the narrator opened
its day-four dispatch with "China's proposed strike" over an action Cuba had
declared. An enum cannot stop it choosing the wrong actor, but it stops it
inventing one, and one line per event keeps each sentence tied to a record.
"""

from __future__ import annotations

import functools
from typing import Literal

from lingo import Context, Engine, Message
from pydantic import ConfigDict, Field, create_model

from .state import RUNG_NAMES, Resolution, WorldState

SYSTEM_PROMPT = (
    "You are a wire-service correspondent covering an international crisis. You "
    "are given the verified facts of the last twenty-four hours and you file the "
    "day's dispatch. Report only what you are given: no speculation, no invented "
    "numbers, no quotations from officials. Attribute every line to the actor the "
    "facts name, never to another one. If nothing material happened, say so."
)

#: Resolutions that never make the news. `escalation` is bookkeeping about the
#: ladder, not an event in the world.
UNREPORTED = frozenset({"escalation"})

MAX_LINES = 5


@functools.lru_cache(maxsize=32)
def dispatch_model(actors: tuple[str, ...]) -> type:
    """A dispatch is lines, each attributed to an actor that exists."""
    line = create_model(
        "Line",
        __config__=ConfigDict(extra="forbid"),
        actor=(
            Literal[actors],  # type: ignore[valid-type]
            Field(description="the actor this sentence is about"),
        ),
        text=(str, Field(description="one sentence, past tense, factual")),
    )
    line.__doc__ = "One sentence of the dispatch, attributed."
    model = create_model(
        "Dispatch",
        __config__=ConfigDict(extra="forbid"),
        lines=(list[line], Field(max_length=MAX_LINES)),  # type: ignore[valid-type]
    )
    model.__doc__ = "The day's wire dispatch: a few attributed sentences."
    return model


async def narrate(state: WorldState, resolutions: list[Resolution], engine: Engine) -> str:
    """Return a short public account of the turn that just resolved."""
    prompt = build_prompt(state, resolutions)
    context = Context([Message.system(SYSTEM_PROMPT), Message.user(prompt)])
    dispatch = await engine.create(context, dispatch_model(tuple(sorted(state.actors))))
    return " ".join(
        f"{line.actor}: {line.text.strip()}" for line in dispatch.lines if line.text.strip()
    )


def build_prompt(state: WorldState, resolutions: list[Resolution]) -> str:
    turn = state.turn - 1
    lines = [f"DAY {turn}. Verified facts:", ""]
    reportable = [r for r in resolutions if r.kind not in UNREPORTED]
    if not reportable:
        lines.append("  Nothing material was resolved.")
    else:
        for resolution in reportable:
            where = f" in {resolution.region}" if resolution.region else ""
            who = f"{resolution.actor}" if resolution.actor else "—"
            lines.append(f"  [{resolution.kind}] {who}{where}: {resolution.reason}")

    lines += ["", "Standing position at the end of the day:"]
    for actor in state.actors.values():
        lines.append(
            f"  {actor.id} ({actor.name}): sustainment {actor.fuel_days:.0f} days, "
            f"international legitimacy {actor.intl_legitimacy:.0f}/100, "
            f"domestic support {actor.domestic_support:.0f}/100, "
            f"highest measure taken so far: {RUNG_NAMES[actor.escalation_rung]}"
        )
    for region in state.regions.values():
        if region.population <= 0:
            continue
        lines.append(
            f"  {region.name}: held by {region.owner or 'nobody'} at "
            f"{region.control:.0f}% control, infrastructure {region.infrastructure:.0f}%, "
            f"civilian distress {region.civilian_distress:.0f}%"
        )
    return "\n".join(lines)
