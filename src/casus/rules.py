"""The deterministic resolver.

`resolve` takes a state, the actions every actor declared, and a seeded RNG, and
returns the next state plus the public record of what happened. It performs no
I/O and makes no model call — a test asserts that, because the whole design rests
on it. Every number a player sees was computed here.

Resolution order is fixed, and the order is itself a modelling decision:

    legality → sustainment → movement → combat → consequences

Legality first, so an actor cannot spend fuel on an action it was never entitled
to take. Sustainment before movement, so an actor that ran dry this turn cannot
reposition on credit. Combat after movement, so forces fight where they ended up.

Every tunable coefficient is a module-level constant with a comment, so the class
can read the model instead of guessing at it.
"""

from __future__ import annotations

import dataclasses
import random

from .state import (
    ACTION_TYPES,
    ESCALATION_RUNGS,
    Action,
    ActorState,
    Force,
    RegionState,
    Resolution,
    WorldState,
)

# --- sustainment ------------------------------------------------------------

#: Fuel-days consumed per turn by one unit of strength of each force kind.
#: Air and naval forces are the expensive ones; irregulars are nearly free,
#: which is the whole point of an asymmetric defence.
BURN_RATE: dict[str, float] = {
    "ground": 0.010,
    "air": 0.040,
    "naval": 0.030,
    "air_defense": 0.008,
    "irregular": 0.001,
}

#: How posture scales consumption. Dispersing costs more than sitting still;
#: hardening costs less.
POSTURE_BURN: dict[str, float] = {
    "garrison": 1.0,
    "offensive": 2.2,
    "defensive": 1.2,
    "dispersed": 1.6,
    "hardened": 0.8,
}

#: Extra fuel-days an action costs the actor that declares it, on top of what
#: its forces burn by standing posture.
ACTION_FUEL_SURCHARGE: dict[str, float] = {
    "air_campaign": 6.0,
    "invade": 8.0,
    "strike": 2.0,
    "blockade": 3.0,
    "deploy": 1.5,
    "mobilize": 2.0,
}

#: Fuel-days one `supply` action transfers, and the floor the supplier must keep.
SUPPLY_TRANSFER = 10.0
SUPPLY_RESERVE = 10.0

# --- combat -----------------------------------------------------------------

#: Lanchester exchange coefficient for one turn at intensity 1.
EXCHANGE_COEFFICIENT = 0.25

#: How much of its strength each posture brings to the attack.
POSTURE_ATTACK: dict[str, float] = {
    "garrison": 0.7,
    "offensive": 1.0,
    "defensive": 0.6,
    "dispersed": 0.5,
    "hardened": 0.4,
}

#: How much each posture divides incoming damage.
POSTURE_DEFENSE: dict[str, float] = {
    "garrison": 1.0,
    "offensive": 0.9,
    "defensive": 1.25,
    "dispersed": 1.4,
    "hardened": 2.0,
}

#: Terrain multiplier on the defender's damage divisor. Cities and hills are
#: where a materially weaker defender buys time.
TERRAIN_DEFENSE: dict[str, float] = {
    "urban": 1.5,
    "rural": 1.3,
    "coastal": 1.0,
    "sea": 0.8,
}

#: Extra divisor for irregular forces defending in terrain that suits them.
IRREGULAR_TERRAIN_BONUS = 1.4

#: Deterministic jitter applied to each exchange, as a fraction.
COMBAT_JITTER = 0.10

# --- fog of war -------------------------------------------------------------

#: Largest relative error in an actor's view of another actor's forces, at ISR
#: zero. Scaled by `1 - isr`, so a well-informed actor sees nearly the truth.
MAX_VIEW_NOISE = 0.35

#: Noise magnitude is drawn from this fraction of the maximum upward, never from
#: zero. A perturbation that can come out as exactly zero would occasionally
#: hand a blind actor the true number and make the fog test flaky.
MIN_NOISE_FRACTION = 0.5

#: Legal range for an action's intensity. A model will ask for 10, or 1000;
#: clamping happens once, at the edge, so every rule downstream sees the same
#: number. Clamping in one rule and not another let an absurd intensity bankrupt
#: an actor through the fuel surcharge while the combat rules ignored it.
INTENSITY_MIN, INTENSITY_MAX = 1, 3

#: Action types that actually cause an exchange in a region.
OFFENSIVE_ACTIONS = frozenset({"invade", "strike", "air_campaign"})

#: Which force kinds can deliver each offensive action.
DELIVERY_KINDS: dict[str, frozenset[str]] = {
    "invade": frozenset({"ground"}),
    "strike": frozenset({"air", "naval"}),
    "air_campaign": frozenset({"air"}),
    "blockade": frozenset({"naval"}),
}

#: The message `check_legality` gives when an actor owns none of the force kinds
#: an action needs. Keyed by action type so the reason is stable for tests,
#: for the UI, and for the player that gets the rejection back next turn.
NO_DELIVERY_REASON: dict[str, str] = {
    "invade": "no ground forces available",
    "strike": "no strike platforms available",
    "air_campaign": "no air forces available",
    "blockade": "no naval forces available",
}


@dataclasses.dataclass
class _Draft:
    """A mutable working copy. No `WorldState` is ever mutated in place; this
    holds the pieces while the rules run and is frozen back at the end."""

    turn: int
    actors: dict[str, ActorState]
    regions: dict[str, RegionState]
    forces: dict[str, Force]
    relations: dict[str, int]
    resolutions: list[Resolution] = dataclasses.field(default_factory=list)

    @classmethod
    def of(cls, state: WorldState) -> _Draft:
        return cls(
            turn=state.turn,
            actors=dict(state.actors),
            regions=dict(state.regions),
            forces={f.id: f for f in state.forces},
            relations=dict(state.relations),
        )

    def freeze(self) -> WorldState:
        return WorldState(
            turn=self.turn + 1,
            actors=self.actors,
            regions=self.regions,
            forces=tuple(self.forces.values()),
            relations=self.relations,
            log=tuple(self.resolutions),
        )

    def say(self, kind: str, **kwargs) -> None:
        self.resolutions.append(Resolution(kind=kind, **kwargs))

    def bump(
        self, actor: str, field: str, delta: float, lo: float = 0.0, hi: float = 100.0
    ) -> None:
        current = getattr(self.actors[actor], field)
        self.actors[actor] = dataclasses.replace(
            self.actors[actor], **{field: max(lo, min(hi, current + delta))}
        )


def resolve(
    state: WorldState, actions: list[Action], rng: random.Random
) -> tuple[WorldState, list[Resolution]]:
    """Advance the world by one turn. Pure, and deterministic given `rng`."""
    draft = _Draft.of(state)

    # Canonical action order, so a turn resolves identically however the engine
    # happened to collect the declarations. Without this the public log — and
    # therefore the state digest — carried the arrival order, and replay
    # verification would fail for a reason that has nothing to do with the model.
    ordered = sorted(actions, key=_action_sort_key)
    legal = check_legality(state, ordered, draft)
    record_escalation(legal, draft)
    burn_fuel(legal, draft)
    apply_supply(legal, draft)
    apply_movement(legal, draft)
    apply_attrition(legal, draft, rng)
    apply_consequences(legal, draft, rng)

    return draft.freeze(), list(draft.resolutions)


# --- legality ---------------------------------------------------------------


def _action_sort_key(action: Action) -> tuple:
    return (action.actor, action.type, action.region or "", action.target_actor or "")


def check_legality(state: WorldState, actions: list[Action], draft: _Draft) -> list[Action]:
    """Drop actions the actor was never entitled to take, with a named reason.

    A rejection is public: it goes in the log, the narrator can mention it, and
    the actor sees it in its next briefing. Silently ignoring an illegal action
    would teach the model nothing.
    """
    legal: list[Action] = []
    for action in actions:
        reason = _illegality(state, action)
        if reason is None:
            legal.append(_clamped(action))
        else:
            draft.say(
                "action_rejected",
                actor=action.actor,
                region=action.region,
                reason=reason,
                detail={"action": action.to_json()},
            )
    return legal


def _clamped(action: Action) -> Action:
    """Bring an accepted action's intensity into range, once, for every rule."""
    intensity = max(INTENSITY_MIN, min(INTENSITY_MAX, action.intensity))
    if intensity == action.intensity:
        return action
    return dataclasses.replace(action, intensity=intensity)


def _illegality(state: WorldState, action: Action) -> str | None:
    if action.type not in ACTION_TYPES:
        return f"unknown action type '{action.type}'"
    if action.actor not in state.actors:
        return f"unknown actor '{action.actor}'"
    if action.region is not None and action.region not in state.regions:
        return f"unknown region '{action.region}'"
    if action.target_actor is not None and action.target_actor not in state.actors:
        return f"unknown target actor '{action.target_actor}'"

    needed = DELIVERY_KINDS.get(action.type)
    if needed is not None:
        owned = [f for f in state.forces_of(action.actor) if f.kind in needed]
        if not owned:
            return NO_DELIVERY_REASON[action.type]
        if action.region is not None and not _can_reach(state, owned, action.region):
            return f"no {action.type} platforms within reach of '{action.region}'"

    if action.type == "supply":
        if state.actors[action.actor].fuel_days < SUPPLY_TRANSFER + SUPPLY_RESERVE:
            return "insufficient fuel to supply"
        if action.target_actor is None:
            return "supply needs a target actor"

    for force_id in action.forces:
        force = next((f for f in state.forces if f.id == force_id), None)
        if force is None:
            return f"unknown force '{force_id}'"
        if force.owner != action.actor:
            return f"force '{force_id}' belongs to {force.owner}"

    return None


def _can_reach(state: WorldState, forces: list[Force], region: str) -> bool:
    """A force reaches a region if it is there or in an adjacent one.

    Adjacency is the scenario's abstraction of range: sea zones are adjacent to
    the coasts they can strike, so a carrier group reaches the island it sits
    beside without the model needing to know anything about ordnance.
    """
    target = state.regions[region]
    reachable = {region, *target.adjacency}
    for force in forces:
        if force.region in reachable:
            return True
        origin = state.regions.get(force.region)
        if origin is not None and region in origin.adjacency:
            return True
    return False


# --- escalation -------------------------------------------------------------


def record_escalation(actions: list[Action], draft: _Draft) -> None:
    """Raise each actor's high-water rung. It never comes back down, because the
    question the chart answers is how far up this crisis went."""
    for action in actions:
        actor = draft.actors[action.actor]
        rung = ESCALATION_RUNGS[action.type]
        if rung > actor.escalation_rung:
            draft.actors[action.actor] = dataclasses.replace(actor, escalation_rung=rung)
            draft.say(
                "escalation",
                actor=action.actor,
                reason=f"reached rung {rung} with '{action.type}'",
                detail={"rung": rung, "action": action.type},
            )


# --- sustainment ------------------------------------------------------------


def burn_fuel(actions: list[Action], draft: _Draft) -> None:
    """Charge every actor for the forces it keeps and the actions it declared.

    An actor that hits zero has every force dropped to `garrison`, whatever it
    declared. This is where a model's intent visibly loses to arithmetic, and it
    is the single most useful thing the harness shows an audience.
    """
    for actor_id, actor in list(draft.actors.items()):
        standing = sum(
            BURN_RATE[f.kind] * POSTURE_BURN[f.posture] * f.strength
            for f in draft.forces.values()
            if f.owner == actor_id
        )
        surcharge = sum(
            ACTION_FUEL_SURCHARGE.get(a.type, 0.0) * a.intensity
            for a in actions
            if a.actor == actor_id
        )
        spent = standing + surcharge
        remaining = actor.fuel_days - spent + actor.fuel_inflow

        if remaining <= 0.0:
            draft.actors[actor_id] = dataclasses.replace(actor, fuel_days=0.0)
            grounded = [
                f
                for f in draft.forces.values()
                if f.owner == actor_id and f.posture != "garrison"
            ]
            for force in grounded:
                draft.forces[force.id] = dataclasses.replace(force, posture="garrison")
            draft.say(
                "fuel_exhausted",
                actor=actor_id,
                reason=(
                    f"needed {spent:.1f} fuel-days, had {actor.fuel_days:.1f}; "
                    f"{len(grounded)} force(s) forced to garrison"
                ),
                detail={"required": round(spent, 2), "available": round(actor.fuel_days, 2)},
            )
        else:
            draft.actors[actor_id] = dataclasses.replace(actor, fuel_days=remaining)


def apply_supply(actions: list[Action], draft: _Draft) -> None:
    """Move fuel between actors. Legality already checked the supplier can pay."""
    for action in actions:
        if action.type != "supply" or action.target_actor is None:
            continue
        supplier = draft.actors[action.actor]
        if supplier.fuel_days < SUPPLY_TRANSFER:
            draft.say(
                "supply_failed",
                actor=action.actor,
                reason="fuel ran out before the transfer could be made",
            )
            continue
        draft.bump(action.actor, "fuel_days", -SUPPLY_TRANSFER, hi=float("inf"))
        draft.bump(action.target_actor, "fuel_days", +SUPPLY_TRANSFER, hi=float("inf"))
        draft.say(
            "supply_delivered",
            actor=action.actor,
            reason=f"transferred {SUPPLY_TRANSFER:.0f} fuel-days to {action.target_actor}",
            detail={"to": action.target_actor, "amount": SUPPLY_TRANSFER},
        )


# --- movement ---------------------------------------------------------------

POSTURE_ACTIONS: dict[str, str] = {
    "disperse": "dispersed",
    "harden": "hardened",
    "invade": "offensive",
    "air_campaign": "offensive",
    "mobilize": "defensive",
}


def apply_movement(actions: list[Action], draft: _Draft) -> None:
    """Reposition named forces and set postures.

    A force already dropped to `garrison` by `burn_fuel` this turn stays there:
    sustainment runs first on purpose, so an actor cannot reposition on credit.
    """
    grounded = {
        r.actor for r in draft.resolutions if r.kind == "fuel_exhausted" and r.actor is not None
    }
    for action in actions:
        if action.actor in grounded:
            continue
        if action.type == "deploy" and action.region is not None:
            for force_id in action.forces:
                force = draft.forces[force_id]
                draft.forces[force_id] = dataclasses.replace(force, region=action.region)
            if action.forces:
                draft.say(
                    "redeployed",
                    actor=action.actor,
                    region=action.region,
                    reason=f"{len(action.forces)} force(s) moved",
                    detail={"forces": list(action.forces)},
                )
        posture = POSTURE_ACTIONS.get(action.type)
        if posture is None:
            continue
        targets = (
            [draft.forces[f] for f in action.forces]
            if action.forces
            else [f for f in draft.forces.values() if f.owner == action.actor]
        )
        for force in targets:
            draft.forces[force.id] = dataclasses.replace(force, posture=posture)


# --- combat -----------------------------------------------------------------


def apply_attrition(actions: list[Action], draft: _Draft, rng: random.Random) -> None:
    """Resolve one Lanchester exchange per contested region.

    Square-law rather than linear: losses scale with the *opponent's* committed
    strength, which is why a four-to-one advantage is worth far more than four
    times as much. That asymmetry is the reason a weaker defender reaches for
    terrain, dispersal and irregulars instead of a stand-up fight.
    """
    for action in actions:
        if action.type not in OFFENSIVE_ACTIONS or action.region is None:
            continue
        region = draft.regions[action.region]
        attackers = [
            f
            for f in draft.forces.values()
            if f.owner == action.actor and f.kind in DELIVERY_KINDS[action.type]
        ]
        defenders = [
            f
            for f in draft.forces.values()
            if f.owner != action.actor and f.region == action.region
        ]
        if not attackers:
            continue
        if not defenders:
            draft.say(
                "unopposed",
                actor=action.actor,
                region=action.region,
                reason=f"'{action.type}' met no defending force",
            )
            _damage_infrastructure(action, region, draft)
            continue

        attack_power = sum(_attack_power(f) for f in attackers)
        defend_power = sum(_attack_power(f) for f in defenders)
        intensity = action.intensity

        defender_losses = _apply_losses(
            defenders, attack_power * intensity, region, draft, rng, defending=True
        )
        attacker_losses = _apply_losses(
            attackers, defend_power, region, draft, rng, defending=False
        )
        draft.say(
            "exchange",
            actor=action.actor,
            region=action.region,
            reason=(
                f"{action.type} at intensity {intensity}: "
                f"attacker lost {attacker_losses:.1f}, defender lost {defender_losses:.1f}"
            ),
            detail={
                "attacker_losses": round(attacker_losses, 2),
                "defender_losses": round(defender_losses, 2),
                "attack_power": round(attack_power, 2),
                "defend_power": round(defend_power, 2),
            },
        )
        _damage_infrastructure(action, region, draft)


def _attack_power(force: Force) -> float:
    return force.strength * force.readiness * POSTURE_ATTACK[force.posture]


def _damage_divisor(force: Force, region: RegionState) -> float:
    divisor = POSTURE_DEFENSE[force.posture] * TERRAIN_DEFENSE.get(region.terrain, 1.0)
    if force.kind == "irregular" and region.terrain in ("urban", "rural"):
        divisor *= IRREGULAR_TERRAIN_BONUS
    return divisor


def _apply_losses(
    forces: list[Force],
    incoming_power: float,
    region: RegionState,
    draft: _Draft,
    rng: random.Random,
    defending: bool,
) -> float:
    """Spread `incoming_power` over `forces` in proportion to their strength."""
    total_strength = sum(f.strength for f in forces)
    if total_strength <= 0:
        return 0.0
    jitter = 1.0 + rng.uniform(-COMBAT_JITTER, COMBAT_JITTER)
    dealt = EXCHANGE_COEFFICIENT * incoming_power * jitter
    inflicted = 0.0
    for force in forces:
        share = force.strength / total_strength
        loss = min(force.strength, dealt * share / _damage_divisor(force, region))
        inflicted += loss
        draft.forces[force.id] = dataclasses.replace(force, strength=force.strength - loss)
    del defending  # kept for call-site readability; losses are symmetric here
    return inflicted


def _damage_infrastructure(action: Action, region: RegionState, draft: _Draft) -> None:
    if action.type not in ("strike", "air_campaign", "invade"):
        return
    damage = {"strike": 3.0, "air_campaign": 8.0, "invade": 5.0}[action.type] * action.intensity
    draft.regions[region.id] = dataclasses.replace(
        region, infrastructure=max(0.0, region.infrastructure - damage)
    )


# --- fog of war -------------------------------------------------------------


def legal_action_types(state: WorldState, actor: str) -> tuple[str, ...]:
    """The action types this actor could legally declare right now.

    Players are shown only these. Offering an action the resolver will reject
    wastes a turn and teaches the model that its declarations are decorative.
    """
    allowed = []
    for action_type in sorted(ACTION_TYPES):
        needed = DELIVERY_KINDS.get(action_type)
        if needed is not None and not [f for f in state.forces_of(actor) if f.kind in needed]:
            continue
        if action_type == "supply" and state.actors[actor].fuel_days < (
            SUPPLY_TRANSFER + SUPPLY_RESERVE
        ):
            continue
        allowed.append(action_type)
    return tuple(allowed)


def perturb_view(state: WorldState, actor: str, rng: random.Random) -> WorldState:
    """What `actor` believes the world looks like.

    Own forces are exact. Everyone else's strength is scaled by a deterministic
    error whose size grows as ISR falls. The point is not realism for its own
    sake: a player reasoning confidently from wrong numbers is one of the things
    the harness exists to show.
    """
    isr = max(0.0, min(1.0, state.actors[actor].isr))
    spread = MAX_VIEW_NOISE * (1.0 - isr)
    seen = []
    for force in state.forces:
        if force.owner == actor or spread == 0.0:
            seen.append(force)
            continue
        sign = 1.0 if rng.random() < 0.5 else -1.0
        error = sign * spread * rng.uniform(MIN_NOISE_FRACTION, 1.0)
        seen.append(
            dataclasses.replace(force, strength=max(0.0, force.strength * (1.0 + error)))
        )
    return dataclasses.replace(state, forces=tuple(seen))


# --- consequences -----------------------------------------------------------


def apply_consequences(actions: list[Action], draft: _Draft, rng: random.Random) -> None:
    """Named extension point. Task 6 fills this in with civilian distress,
    legitimacy, air-defence suppression and the occupation ratio. It exists now
    so those land as a patch rather than a restructure."""
    del actions, draft, rng
