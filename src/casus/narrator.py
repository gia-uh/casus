"""Turn narration. Reads the resolved world, writes prose, changes nothing.

The narrator exists because a table of resolution records is unreadable to
anyone who did not write it, and the audience for this harness is not engineers.
It is given the state after the resolver has finished and asked to describe it.

It has no write path to state, and `test_narrator_cannot_mutate_state` asserts
the state digest is unchanged across the call. That test is the whole reason this
is a separate module: the moment a model is allowed to adjust a number "for
narrative reasons", every figure in the run stops being auditable.
"""

from __future__ import annotations

from collections.abc import Callable

from .llm import LLMResult, complete
from .state import RUNG_NAMES, Resolution, WorldState

SYSTEM_PROMPT = (
    "You are a wire-service correspondent covering an international crisis. You "
    "are given the verified facts of the last twenty-four hours and you write the "
    "news ticker: three to five short sentences, past tense, no speculation, no "
    "invented numbers, no quotations from officials. Report only what you are "
    "given. If nothing material happened, say so plainly."
)

#: Resolutions that never make the news. `escalation` is a bookkeeping event
#: about the ladder, not a thing that happened in the world.
UNREPORTED = frozenset({"escalation"})


def narrate(
    state: WorldState,
    resolutions: list[Resolution],
    call: Callable[..., LLMResult] = complete,
    model: str = "",
) -> str:
    """Return a short public account of the turn that just resolved."""
    prompt = build_prompt(state, resolutions)
    try:
        result = call(
            model,
            [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001 — narration is decoration; a run must not die for it
        return f"(no dispatch this turn: {type(exc).__name__})"
    return _plain_text(result.text)


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
            f"  {actor.name}: sustainment {actor.fuel_days:.0f} days, "
            f"international legitimacy {actor.intl_legitimacy:.0f}/100, "
            f"domestic support {actor.domestic_support:.0f}/100, "
            f"highest measure taken so far: {RUNG_NAMES[actor.escalation_rung]}"
        )
    for region in state.regions.values():
        if region.population <= 0:
            continue
        lines.append(
            f"  {region.name}: held by {region.owner or 'nobody'} at {region.control:.0f}% control, "
            f"infrastructure {region.infrastructure:.0f}%, "
            f"civilian distress {region.civilian_distress:.0f}%"
        )
    return "\n".join(lines)


def _plain_text(text: str) -> str:
    """Strip a reasoning block and any JSON the model decided to send anyway."""
    from .players import THINK_BLOCK

    cleaned = THINK_BLOCK.sub("", text).strip()
    if cleaned.startswith(("{", "[")):
        return "(the correspondent filed structured data instead of prose)"
    return cleaned
