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

# --- air defence ------------------------------------------------------------

#: Damage a suppression campaign does to air defences per turn, per point of
#: attacker air power, per point of intensity. Calibrated so a 60-point battery
#: under a sustained intensity-3 campaign by a 100-point air force falls below
#: the floor on the fourth turn, matching the four-to-five days publicly
#: reported for the opening of the 2026 Iran campaign.
SUPPRESSION_COEFFICIENT = 0.055

#: Below this strength an air defence no longer imposes a penalty on strikes.
#: Crossing it is the single most consequential threshold in the model: after it
#: the attacker overflies freely and switches to cheap munitions.
SUPPRESSION_FLOOR = 10.0

#: How much surviving air defence divides incoming strike damage, per 100 points
#: of its strength.
AIR_DEFENCE_PROTECTION = 0.9

# --- occupation -------------------------------------------------------------

#: One member of the security forces per this many inhabitants is the
#: stability-operations rule of thumb. CSIS applies it to Cuba to arrive at an
#: external force of about 100,000 for ten million people, assuming half the
#: total comes from indigenous police. This function returns the TOTAL; how much
#: of it is indigenous is a scenario question, not a rule.
INHABITANTS_PER_SECURITY_MEMBER = 50

#: Headcount one point of abstract force strength stands for.
TROOPS_PER_STRENGTH_POINT = 1000

#: Control lost per turn by an occupier below the required ratio, at the point
#: where it has none of the force it needs. Scaled by how short it falls.
CONTROL_DECAY_MAX = 12.0

#: Irregular strength that regenerates per turn in an under-occupied region.
INSURGENT_REGENERATION = 2.5

# --- civilian consequences --------------------------------------------------

#: Civilian distress added per turn, per point of missing infrastructure.
DISTRESS_PER_DAMAGE_POINT = 0.25

#: Distress added per turn when the region owner has run out of fuel entirely.
DISTRESS_FROM_FUEL_EXHAUSTION = 6.0

#: International legitimacy an attacker loses per turn, per point of distress in
#: a region it is striking.
LEGITIMACY_COST_PER_DISTRESS = 0.08

#: Domestic support a region's owner loses per turn, per point of distress.
SUPPORT_COST_PER_DISTRESS = 0.05

#: Rung at or above which an action counts as causing civilian harm.
HARM_RUNG = 5

#: Legal range for an action's intensity. A model will ask for 10, or 1000;
#: clamping happens once, at the edge, so every rule downstream sees the same
#: number. Clamping in one rule and not another let an absurd intensity bankrupt
#: an actor through the fuel surcharge while the combat rules ignored it.
INTENSITY_MIN, INTENSITY_MAX = 1, 3

#: Action types that actually cause an exchange in a region.
OFFENSIVE_ACTIONS = frozenset({"invade", "strike", "air_campaign"})

#: Action types for which `region` means something. For the rest — a statement,
#: a negotiation, a sanction — a region is decorative, and both live models kept
#: attaching one ("global", "international"). Rejecting those crowded the real
#: rejections out of the log, so a decorative region is dropped instead.
REGIONAL_ACTIONS = frozenset(
    {
        "invade",
        "strike",
        "air_campaign",
        "blockade",
        "deploy",
        "disperse",
        "harden",
        "cyber",
        "covert",
    }
)

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
    """Normalise an accepted action, once, for every rule downstream.

    Clamps intensity into range and drops a region on an action that has no use
    for one, so no later rule has to wonder whether it was validated.
    """
    intensity = max(INTENSITY_MIN, min(INTENSITY_MAX, action.intensity))
    region = action.region if action.type in REGIONAL_ACTIONS else None
    if intensity == action.intensity and region == action.region:
        return action
    return dataclasses.replace(action, intensity=intensity, region=region)


def _illegality(state: WorldState, action: Action) -> str | None:
    if action.type not in ACTION_TYPES:
        return f"unknown action type '{action.type}'"
    if action.actor not in state.actors:
        return f"unknown actor '{action.actor}'"
    if (
        action.region is not None
        and action.type in REGIONAL_ACTIONS
        and action.region not in state.regions
    ):
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
        all_defenders = [
            f
            for f in draft.forces.values()
            if f.owner != action.actor and f.region == action.region
        ]
        # Air defences are hunted, not slugged out with: against an air or naval
        # attacker they take suppression damage on their own schedule and stay
        # out of the exchange. Leaving them in made a battery evaporate in one
        # turn, which contradicts every published account of a SEAD campaign.
        by_air = DELIVERY_KINDS[action.type] <= frozenset({"air", "naval"})
        defenders = [f for f in all_defenders if not (by_air and f.kind == "air_defense")]
        if by_air:
            suppress_air_defense(action, all_defenders, draft)
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

        attack_power = sum(_attack_power(f) for f in attackers) / _air_defence_divisor(
            all_defenders if by_air else []
        )
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


def reachable_regions(state: WorldState, actor: str, action_type: str) -> tuple[str, ...]:
    """Regions this actor can currently deliver `action_type` against.

    Offered to players explicitly. The information is derivable from the map and
    the order of battle already in the prompt, but a 32B model reliably fails to
    derive it: in the first live smoke run one repeated an out-of-reach air
    campaign three turns running, having moved its carrier away from the target
    in the belief that this enabled the strike. Stating reach outright makes any
    remaining failure the model's and not an information gap.
    """
    needed = DELIVERY_KINDS.get(action_type)
    if needed is None:
        return tuple(sorted(state.regions))
    owned = [f for f in state.forces_of(actor) if f.kind in needed]
    if not owned:
        return ()
    return tuple(sorted(r for r in state.regions if _can_reach(state, owned, r)))


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
    """Everything that follows from the fighting rather than being the fighting."""
    del rng  # consequences are fully determined; the randomness is in the exchange
    decay_control(draft)
    update_distress_and_legitimacy(actions, draft)


# --- air defence ------------------------------------------------------------


def suppress_air_defense(action: Action, defenders: list[Force], draft: _Draft) -> None:
    """Degrade the air defences in a region under air or naval attack.

    Deterministic, with no jitter. The point of this rule is the threshold, and a
    threshold whose crossing turn wobbles by one is useless both as a teaching
    figure and as a test.
    """
    batteries = [f for f in defenders if f.kind == "air_defense"]
    if not batteries:
        return
    attackers = [
        f
        for f in draft.forces.values()
        if f.owner == action.actor and f.kind in DELIVERY_KINDS[action.type]
    ]
    air_power = sum(_attack_power(f) for f in attackers)
    if air_power <= 0:
        return

    before = sum(f.strength for f in batteries)
    damage = SUPPRESSION_COEFFICIENT * air_power * action.intensity
    total = sum(f.strength for f in batteries)
    for battery in batteries:
        share = battery.strength / total if total else 0.0
        draft.forces[battery.id] = dataclasses.replace(
            battery, strength=max(0.0, battery.strength - damage * share)
        )
    after = sum(draft.forces[f.id].strength for f in batteries)

    draft.say(
        "air_defence_degraded",
        actor=action.actor,
        region=action.region,
        reason=f"air defences reduced from {before:.1f} to {after:.1f}",
        detail={"before": round(before, 2), "after": round(after, 2)},
    )
    if before >= SUPPRESSION_FLOOR > after:
        draft.say(
            "air_defence_suppressed",
            actor=action.actor,
            region=action.region,
            reason=(
                f"air defences fell below {SUPPRESSION_FLOOR:.0f}; "
                f"the airspace over {action.region} is now open"
            ),
            detail={"floor": SUPPRESSION_FLOOR, "remaining": round(after, 2)},
        )


def _air_defence_divisor(defenders: list[Force]) -> float:
    """How much surviving air defence blunts a strike. 1.0 once suppressed."""
    strength = sum(f.strength for f in defenders if f.kind == "air_defense")
    if strength < SUPPRESSION_FLOOR:
        return 1.0
    return 1.0 + AIR_DEFENCE_PROTECTION * strength / 100.0


# --- occupation -------------------------------------------------------------


def occupation_requirement(population: int) -> int:
    """Security-force headcount needed to hold a population without an active
    insurgency. Returns the total, indigenous and external together."""
    return population // INHABITANTS_PER_SECURITY_MEMBER


def decay_control(draft: _Draft) -> None:
    """An occupier short of the ratio loses control, and insurgents regenerate.

    This is the rule that makes taking ground different from holding it. A model
    that captures a city and then watches the number fall every turn is being
    shown, not told, why the published invasion estimates are what they are.
    """
    for region_id, region in list(draft.regions.items()):
        occupied = bool(region.country) and region.owner not in ("", region.country)
        if not occupied or region.population <= 0:
            continue
        required = occupation_requirement(region.population)
        present = (
            sum(
                f.strength
                for f in draft.forces.values()
                if f.owner == region.owner
                and f.kind in ("ground", "irregular")
                and f.region == region_id
            )
            * TROOPS_PER_STRENGTH_POINT
        )
        if present >= required:
            continue
        shortfall = 1.0 - (present / required if required else 1.0)
        draft.regions[region_id] = dataclasses.replace(
            region, control=max(0.0, region.control - CONTROL_DECAY_MAX * shortfall)
        )
        draft.say(
            "insufficient_occupation_force",
            actor=region.owner,
            region=region_id,
            reason=(
                f"holding {region.name} needs {required:,} security personnel; "
                f"{int(present):,} are present, so control is slipping"
            ),
            detail={
                "required": required,
                "present": int(present),
                "shortfall": round(shortfall, 3),
            },
        )
        _regenerate_insurgents(region, draft)


def _regenerate_insurgents(region: RegionState, draft: _Draft) -> None:
    """Under-occupied ground grows irregulars loyal to the original owner."""
    if not region.country or region.country == region.owner:
        return
    existing = [
        f
        for f in draft.forces.values()
        if f.owner == region.country and f.kind == "irregular" and f.region == region.id
    ]
    if existing:
        force = existing[0]
        draft.forces[force.id] = dataclasses.replace(
            force, strength=force.strength + INSURGENT_REGENERATION
        )
        return
    new_id = f"{region.country}-insurgents-{region.id}"
    if new_id in draft.forces:
        return
    draft.forces[new_id] = Force(
        id=new_id,
        owner=region.country,
        kind="irregular",
        strength=INSURGENT_REGENERATION,
        readiness=0.4,
        region=region.id,
        posture="dispersed",
    )
    draft.say(
        "insurgency_formed",
        actor=region.country,
        region=region.id,
        reason=f"irregular resistance has appeared in {region.name}",
    )


# --- civilian consequences --------------------------------------------------


def update_distress_and_legitimacy(actions: list[Action], draft: _Draft) -> None:
    """Civilian suffering, and who pays for it politically.

    The two costs run on different curves on purpose. Distress in a region costs
    the attacker international legitimacy and the region's owner domestic
    support: the same suffering is a liability for both sides, which is the
    dynamic that makes an attritional pressure campaign a race rather than a
    siege.
    """
    exhausted = {
        r.actor for r in draft.resolutions if r.kind == "fuel_exhausted" and r.actor is not None
    }
    for region_id, region in list(draft.regions.items()):
        if region.population <= 0:
            continue
        added = DISTRESS_PER_DAMAGE_POINT * (100.0 - region.infrastructure)
        if region.owner in exhausted:
            added += DISTRESS_FROM_FUEL_EXHAUSTION
        if added <= 0:
            continue
        draft.regions[region_id] = dataclasses.replace(
            region, civilian_distress=min(100.0, region.civilian_distress + added)
        )

    for action in actions:
        if ESCALATION_RUNGS[action.type] < HARM_RUNG or action.region is None:
            continue
        region = draft.regions.get(action.region)
        if region is None or region.population <= 0:
            continue
        cost = LEGITIMACY_COST_PER_DISTRESS * region.civilian_distress
        if cost <= 0:
            continue
        draft.bump(action.actor, "intl_legitimacy", -cost)
        draft.say(
            "legitimacy_cost",
            actor=action.actor,
            region=action.region,
            reason=(
                f"civilian distress in {region.name} cost {action.actor} "
                f"{cost:.1f} points of international legitimacy"
            ),
            detail={"cost": round(cost, 2), "distress": round(region.civilian_distress, 1)},
        )

    for region in draft.regions.values():
        if region.population <= 0 or not region.owner:
            continue
        if region.owner not in draft.actors:
            continue
        cost = SUPPORT_COST_PER_DISTRESS * region.civilian_distress
        if cost > 0:
            draft.bump(region.owner, "domestic_support", -cost)
