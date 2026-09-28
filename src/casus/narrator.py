"""Turn narration. Reads the resolved world, writes prose, changes nothing.

The narrator exists because a table of resolution records is unreadable to
anyone who did not write it, and the audience for this harness is not engineers.

It is a separate module for one reason: `test_narrator_cannot_mutate_state`. The
moment a model is allowed to adjust a number for narrative reasons, every figure
in the run stops being auditable.

**The model does not write the subject.** It is given the facts of the turn, in
order, and returns one predicate per fact; the engine puts the actor in front,
taken from the resolution record. This is not a style choice. Letting the model
name the actor produced three misattributions in twelve dispatches — an American
air campaign reported as Cuban, twice — and an enum on an `actor` field did not
help, because the enum stops it inventing a country and not choosing the wrong
one. Pairing positionally removes the choice.
"""

from __future__ import annotations

import functools

from lingo import Context, Engine, Message
from pydantic import ConfigDict, Field, create_model

from .state import RUNG_NAMES, Resolution, WorldState

SYSTEM_PROMPT = (
    "You are a wire-service correspondent covering an international crisis. You "
    "are given the verified facts of the last twenty-four hours, numbered. For "
    "each fact, in the same order, write the predicate of one short past-tense "
    "sentence — what happened — WITHOUT naming the actor and without a subject, "
    "because the subject is added for you. Example: for a fact about a fuel "
    "transfer, write 'transferred ten days of fuel to Cuba', not 'Russia "
    "transferred ten days of fuel to Cuba'. Report only what you are given: no "
    "speculation, no invented numbers, no quotations."
)

#: Resolutions that never make the news. `escalation` is bookkeeping about the
#: ladder, not an event in the world.
UNREPORTED = frozenset({"escalation"})

#: Facts reported per turn. A resolver can emit two dozen records in a heavy
#: turn, and a wire dispatch is not a log.
MAX_FACTS = 5

LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French"}


@functools.lru_cache(maxsize=16)
def dispatch_model(count: int) -> type:
    """Exactly `count` predicates, so fact *i* and predicate *i* are the same event.

    The length is pinned at both ends: a model that returns four predicates for
    five facts would shift every subject by one, which is the failure this whole
    design exists to prevent, and it would look plausible on screen.
    """
    model = create_model(
        "Dispatch",
        __config__=ConfigDict(extra="forbid"),
        predicates=(
            list[str],
            Field(
                min_length=count,
                max_length=count,
                description="one predicate per numbered fact, in the same order",
            ),
        ),
    )
    model.__doc__ = "The day's wire dispatch: one predicate per fact, in order."
    return model


def reportable(resolutions: list[Resolution]) -> list[Resolution]:
    return [r for r in resolutions if r.kind not in UNREPORTED][:MAX_FACTS]


async def narrate(
    state: WorldState,
    resolutions: list[Resolution],
    engine: Engine,
    language: str = "en",
) -> str:
    """Return a short public account of the turn that just resolved."""
    facts = reportable(resolutions)
    if not facts:
        return ""

    prompt = build_prompt(state, facts, language)
    context = Context([Message.system(SYSTEM_PROMPT), Message.user(prompt)])
    dispatch = await engine.create(context, dispatch_model(len(facts)))

    names = {a.id: a.name for a in state.actors.values()}
    lines = []
    for fact, predicate in zip(facts, dispatch.predicates, strict=True):
        text = " ".join(str(predicate).split())
        if not text:
            continue
        subject = names.get(fact.actor or "", "")
        sentence = f"{subject} {text}".strip() if subject else text
        lines.append(sentence if sentence.endswith((".", "!", "?")) else sentence + ".")
    return " ".join(lines)


def build_prompt(state: WorldState, facts: list[Resolution], language: str) -> str:
    turn = state.turn - 1
    lines = [f"DAY {turn}. Verified facts, numbered:", ""]
    for index, fact in enumerate(facts, start=1):
        where = f" in {fact.region}" if fact.region else ""
        lines.append(f"  {index}. [{fact.kind}]{where}: {fact.reason}")

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
            f"  {region.name}: held by {region.owner or 'nobody'} at "
            f"{region.control:.0f}% control, infrastructure {region.infrastructure:.0f}%, "
            f"civilian distress {region.civilian_distress:.0f}%"
        )

    lines += [
        "",
        (
            f"Write exactly {len(facts)} predicates, one per numbered fact, in "
            "order. No subject, no actor name — the subject is added for you."
        ),
    ]
    if language != "en":
        # At the end of the user message, not only in the system prompt: the facts
        # are English, and a correspondent given English facts and a distant
        # instruction drifted back into English in one dispatch of twelve.
        lines.append(
            f"Write them in {LANGUAGE_NAMES.get(language, language)}, "
            "including place names where they have a common form in that language."
        )
    return "\n".join(lines)
