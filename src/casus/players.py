"""One language model per actor, behind a closed action vocabulary.

A player sees its own briefing, a deliberately imperfect view of the world, and
the list of actions it is actually entitled to take. It returns JSON. Everything
it says about *why* is kept verbatim in the transcript, because that text is the
teaching material; everything it says about *how much* is ignored, because the
resolver owns the numbers.

The prompt is built by one function that returns a string, so a test can read it
and the replayer can show the audience exactly what the model saw.
"""

from __future__ import annotations

import dataclasses
import json
import random
import re
from collections.abc import Callable

from . import rules
from .llm import LLMResult, complete
from .state import RUNG_NAMES, Action, WorldState

#: Most actions an actor may declare in one turn. More than this and a single
#: turn stops being a decision and starts being a wish list.
MAX_ACTIONS_PER_TURN = 3

#: Qwen-class models emit a reasoning block before the answer. Stripping it is
#: not cosmetic: the block frequently contains draft JSON that a naive parser
#: picks up instead of the final answer.
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)

ACTION_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["actions", "rationale", "assessment"],
    "properties": {
        "actions": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_ACTIONS_PER_TURN,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type"],
                "properties": {
                    "type": {"type": "string"},
                    "region": {"type": ["string", "null"]},
                    "target_actor": {"type": ["string", "null"]},
                    "forces": {"type": "array", "items": {"type": "string"}},
                    "intensity": {"type": "integer", "minimum": 1, "maximum": 3},
                },
            },
        },
        "rationale": {"type": "string"},
        "assessment": {"type": "string"},
    },
}


class SchemaViolation(ValueError):
    """The model's JSON did not describe a legal declaration."""


@dataclasses.dataclass(frozen=True)
class PlayerTurn:
    actions: tuple[Action, ...]
    rationale: str
    assessment: str
    prompt: str
    raw: dict
    schema_failures: int = 0
    model: str = ""
    tokens: tuple[int, int] = (0, 0)


@dataclasses.dataclass(frozen=True)
class Player:
    actor_id: str
    briefing: str
    model: str

    def decide(
        self,
        state: WorldState,
        rng: random.Random,
        call: Callable[..., LLMResult] = complete,
    ) -> PlayerTurn:
        """Ask the model for this turn's declaration. Never raises.

        A model that answers with prose, or with an action it was not offered,
        gets exactly one more chance with the validation error quoted back. After
        that the actor holds. Crashing the run because a 32B model wandered off
        the schema would make the harness useless for the thing it is for.
        """
        view = rules.perturb_view(state, self.actor_id, rng)
        legal = rules.legal_action_types(state, self.actor_id)
        prompt = build_prompt(self.actor_id, self.briefing, view, legal)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        failures = 0
        last: LLMResult | None = None
        for attempt in (1, 2):
            last = call(self.model, messages, schema=ACTION_SCHEMA)
            try:
                actions, rationale, assessment = parse_declaration(
                    last.text, self.actor_id, legal
                )
            except SchemaViolation as exc:
                failures += 1
                if attempt == 2:
                    break
                messages = messages + [
                    {"role": "assistant", "content": last.text},
                    {
                        "role": "user",
                        "content": (
                            f"That was rejected: {exc}. Reply with valid JSON matching "
                            f"the schema and nothing else — no prose, no code fence."
                        ),
                    },
                ]
                continue
            return PlayerTurn(
                actions=actions,
                rationale=rationale,
                assessment=assessment,
                prompt=prompt,
                raw=last.raw,
                schema_failures=failures,
                model=last.model,
                tokens=(last.prompt_tokens, last.completion_tokens),
            )

        return PlayerTurn(
            actions=(Action(actor=self.actor_id, type="hold"),),
            rationale="(no valid declaration; the actor holds)",
            assessment="",
            prompt=prompt,
            raw=last.raw if last else {},
            schema_failures=failures,
            model=last.model if last else self.model,
            tokens=(last.prompt_tokens, last.completion_tokens) if last else (0, 0),
        )


SYSTEM_PROMPT = (
    "You are the national command authority of one state in a strategic crisis "
    "simulation used for teaching. You decide policy, not arithmetic: an external "
    "resolver computes every material outcome. Answer only with JSON matching the "
    "schema you are given. Argue for your choice in `rationale` in at most four "
    "sentences, and state what you believe your opponent will do next in "
    "`assessment`."
)


def build_prompt(actor_id: str, briefing: str, view: WorldState, legal: tuple[str, ...]) -> str:
    """Assemble what one actor sees. Returned as a string on purpose: it goes in
    the transcript verbatim and the replayer shows it to the audience."""
    me = view.actors[actor_id]
    lines = [
        f"TURN {view.turn}. You are {me.name} ({actor_id}).",
        "",
        "YOUR STANDING ORDERS",
        briefing.strip(),
        "",
        "YOUR POSITION",
        f"  sustainment: {me.fuel_days:.0f} fuel-days ({_fuel_band(me.fuel_days)})",
        f"  munitions {me.munitions:.0f}/100 · political capital {me.political_capital:.0f}/100",
        (
            f"  domestic support {me.domestic_support:.0f}/100 · "
            f"international legitimacy {me.intl_legitimacy:.0f}/100"
        ),
        f"  intelligence quality: {_isr_band(me.isr)}",
        (
            f"  highest rung you have reached: {me.escalation_rung} "
            f"({RUNG_NAMES[me.escalation_rung]})"
        ),
        "",
        "YOUR FORCES (exact)",
    ]
    own = view.forces_of(actor_id)
    lines += [f"  {_force_line(f)}" for f in own] or ["  none"]

    lines += ["", "OTHER ACTORS"]
    for other_id, other in view.actors.items():
        if other_id == actor_id:
            continue
        lines.append(
            f"  {other.name} ({other_id}): sustainment {_fuel_band(other.fuel_days)}, "
            f"legitimacy {_band(other.intl_legitimacy)}, "
            f"highest rung {other.escalation_rung} ({RUNG_NAMES[other.escalation_rung]})"
        )

    lines += [
        "",
        f"FORCES YOU CAN SEE (estimates — your intelligence is {_isr_band(me.isr)})",
    ]
    foreign = [f for f in view.forces if f.owner != actor_id]
    lines += [f"  {_force_line(f)} (estimate)" for f in foreign] or ["  none detected"]

    lines += ["", "MAP"]
    for region in view.regions.values():
        holder = region.owner or "unclaimed"
        lines.append(
            f"  {region.id} ({region.name}, {region.terrain}, pop {region.population:,}): "
            f"held by {holder}, control {region.control:.0f}%, "
            f"infrastructure {region.infrastructure:.0f}%, "
            f"civilian distress {region.civilian_distress:.0f}%"
            + (f", adjacent to {', '.join(region.adjacency)}" if region.adjacency else "")
        )

    if view.log:
        lines += ["", "WHAT HAPPENED LAST TURN"]
        lines += [f"  {_resolution_line(r)}" for r in view.log]

    lines += [
        "",
        "ACTIONS AVAILABLE TO YOU THIS TURN",
        "  " + ", ".join(legal),
    ]
    for action_type in legal:
        if action_type not in rules.DELIVERY_KINDS:
            continue
        reach = rules.reachable_regions(view, actor_id, action_type)
        lines.append(
            f"  {action_type} can reach: "
            + (", ".join(reach) if reach else "nowhere right now")
        )
    lines += [
        "",
        (
            f"Declare between 1 and {MAX_ACTIONS_PER_TURN} actions. Use only the types "
            "listed above; anything else is discarded. `region` must be one of the map "
            "identifiers. `intensity` is 1, 2 or 3."
        ),
    ]
    return "\n".join(lines)


def parse_declaration(
    text: str, actor_id: str, legal: tuple[str, ...]
) -> tuple[tuple[Action, ...], str, str]:
    """Turn a completion into actions, or explain precisely what was wrong."""
    payload = extract_json(text)
    if payload is None:
        raise SchemaViolation("the reply contained no JSON object")
    if not isinstance(payload, dict):
        raise SchemaViolation(f"expected a JSON object, got {type(payload).__name__}")

    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise SchemaViolation("'actions' must be a non-empty array")
    if len(raw_actions) > MAX_ACTIONS_PER_TURN:
        raise SchemaViolation(f"at most {MAX_ACTIONS_PER_TURN} actions per turn")

    actions = []
    for item in raw_actions:
        if not isinstance(item, dict):
            raise SchemaViolation("each action must be an object")
        action_type = item.get("type")
        if action_type not in legal:
            raise SchemaViolation(
                f"'{action_type}' is not available to you; choose from {', '.join(legal)}"
            )
        forces = item.get("forces") or []
        if not isinstance(forces, list):
            raise SchemaViolation("'forces' must be an array of force identifiers")
        actions.append(
            Action(
                actor=actor_id,
                type=action_type,
                region=item.get("region") or None,
                target_actor=item.get("target_actor") or None,
                forces=tuple(str(f) for f in forces),
                intensity=_as_intensity(item.get("intensity", 1)),
            )
        )
    return tuple(actions), str(payload.get("rationale", "")), str(payload.get("assessment", ""))


def extract_json(text: str) -> object | None:
    """Find the model's answer inside whatever it actually sent.

    Handles a reasoning block, a code fence, and prose either side. Scans from
    the end, because when a model emits more than one object the last one is the
    answer and the earlier ones are its drafts.
    """
    cleaned = FENCE.sub("", THINK_BLOCK.sub("", text)).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for start, end in reversed(list(_top_level_object_spans(cleaned))):
        try:
            return json.loads(cleaned[start:end])
        except json.JSONDecodeError:
            continue
    return None


def _top_level_object_spans(text: str):
    """Yield `(start, end)` for each brace-balanced object at nesting depth zero.

    A naive backward scan for `{` finds the innermost object first — given
    `{"actions":[{"type":"hold"}]}` it returns `{"type":"hold"}`, which parses
    cleanly and is the wrong answer. Matching braces properly, and skipping
    braces inside string literals, is the only way to get the outer object.
    """
    depth = 0
    start = None
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                yield start, index + 1
                start = None


def _as_intensity(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1


def _force_line(force) -> str:
    return (
        f"{force.id}: {force.kind} strength {force.strength:.0f} in {force.region}, "
        f"posture {force.posture}, readiness {force.readiness:.0%}"
    )


def _resolution_line(resolution) -> str:
    where = f" [{resolution.region}]" if resolution.region else ""
    who = f"{resolution.actor}: " if resolution.actor else ""
    return f"{who}{resolution.kind}{where} — {resolution.reason}"


def _fuel_band(days: float) -> str:
    if days <= 0:
        return "exhausted"
    if days < 15:
        return "critical"
    if days < 45:
        return "strained"
    return "sufficient"


def _isr_band(isr: float) -> str:
    if isr >= 0.8:
        return "excellent"
    if isr >= 0.5:
        return "adequate"
    if isr >= 0.25:
        return "poor"
    return "very poor"


def _band(value: float) -> str:
    if value >= 70:
        return "high"
    if value >= 40:
        return "moderate"
    return "low"
