"""The reference ruleset: v1's physics, ported onto the rule surface.

Sustainment, Lanchester attrition, air-defence suppression, mobilisation,
supply, movement, the escalation high-water mark, the occupation ratio,
civilian distress and legitimacy. The coefficients and their comments came
across from v1 unchanged, because the comments are the provenance.

The port is verbatim, and the recovery rules at the end repair v1's ratchet;
with their three rates at zero the ruleset is v1 exactly. Where v1 read a value captured before a change in the
same turn, the port captures it too, so the arithmetic lands on the same bits.

Resolution order, as in v1:

    legality → upkeep (escalation, fuel, supply) → movement (mobilisation,
    movement) → contest (attrition) → consequences (occupation, distress)
"""

from casus.ruleset import offer, rule, view

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

#: Force strength one `mobilize` action calls up, drawn from the actor's reserve
#: pool. Published think-tank estimates put an invasion of a ten-million-person
#: country at around 100,000 personnel, months to assemble and visible long
#: before it begins; at this rate and one point per thousand troops, that is a
#: dozen consecutive turns of open mobilisation, which is the point.
REINFORCEMENT_PER_MOBILIZE = 8.0

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
#: reported for the opening phase of recent air campaigns.
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
#: stability-operations rule of thumb, from *Parameters*. Applied to ten million
#: people it gives 200,000 in total, which think-tank estimates halve to about
#: 100,000 external on the assumption that indigenous police supply the rest.
#: This function returns the TOTAL; how much of it is indigenous is a scenario
#: question, not a rule.
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

# --- recovery ---------------------------------------------------------------
#
# v1 had none of these, so distress could only rise and domestic support could
# only fall: the ratchet that drove Cuban support to zero by turn six with every
# actor holding. The three rates are design choices with no published source,
# and SOURCES.md says so. They were chosen so that, in the Caribbean with every
# actor holding, the crisis bottoms out and starts to turn inside the scenario's
# twelve days: Cuban distress peaks on day 5 and support, having fallen from 52
# to about 22, rises again on day 12. Setting all three to zero gives back v1
# exactly, which is how the acceptance test replays v1's recording.

#: Fraction of the gap to full infrastructure rebuilt per turn in a place not
#: attacked this turn. About half the damage is repaired in eleven days.
RECONSTRUCTION_RATE = 0.06

#: Fraction of civilian distress that eases per turn in a quiet place. Damage
#: still adds 0.25 per missing point each turn, so distress settles near 1.7
#: times the missing infrastructure and falls as the place is rebuilt.
DISTRESS_RELIEF_RATE = 0.15

#: Fraction of the gap to its baseline that an actor's domestic support recovers
#: per turn. Against the distress cost of 0.05 per point, summed over the
#: actor's places, support settles near baseline minus a fifth of that sum.
SUPPORT_RECOVERY_RATE = 0.25

#: Actions that damage the place they target, and so stop it recovering this turn.
DAMAGING_ACTIONS = frozenset({"strike", "air_campaign", "invade"})


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


#: Postures an action puts its forces into.
POSTURE_ACTIONS: dict[str, str] = {
    "disperse": "dispersed",
    "harden": "hardened",
    "invade": "offensive",
    "air_campaign": "offensive",
    "mobilize": "defensive",
}


#: Every action type the reference declares, and the ones that take a place.
#: `scenario.yaml` declares the same vocabulary; `offer` needs it here to say
#: what may be declared.
ACTION_TYPES = (
    "air_campaign", "blockade", "concede", "covert", "cyber", "deploy", "disperse", "harden",
    "hold", "invade", "mobilize", "negotiate", "sanction", "statement", "strike", "supply",
)  # fmt: skip
PLACED = frozenset(
    {"invade", "strike", "air_campaign", "blockade", "deploy", "disperse", "harden", "cyber",
     "covert"}
)  # fmt: skip


# --- legality ---------------------------------------------------------------


@rule(phase="legality", on=ACTION_TYPES)
def entitlement(s, a):
    """Reject what the actor was never entitled to take, with a named reason.

    A rejection is public: it goes in the log, the narrator can mention it, and
    the actor sees it next turn. The engine has already rejected unknown action
    types, actors, places and targets; these are the checks only this physics
    can make.
    """
    reason = _illegality(s, a)
    if reason is not None:
        s.reject(reason)


def _illegality(s, a):
    needed = DELIVERY_KINDS.get(a.type)
    if needed is not None:
        owned = [f for f in s.find(owner=a.actor) if f.kind in needed]
        if not owned:
            return NO_DELIVERY_REASON[a.type]
        if a.place is not None and not _can_reach(s, owned, a.place):
            return f"no {a.type} platforms within reach of '{a.place}'"

    if a.type == "supply":
        if s.actor(a.actor).fuel_days < SUPPLY_TRANSFER + SUPPLY_RESERVE:
            return "insufficient fuel to supply"
        if a.target is None:
            return "supply needs a target actor"

    for ident in a.entities:
        found = [f for f in s.entities if f.id == ident]
        if not found:
            return f"unknown force '{ident}'"
        if found[0].owner != a.actor:
            return f"force '{ident}' belongs to {found[0].owner}"
    return None


def _can_reach(s, forces, place):
    """A force reaches a place if it is there or in an adjacent one.

    Adjacency is the scenario's abstraction of range: sea zones are adjacent to
    the coasts they can strike, so a carrier group reaches the island it sits
    beside without the model needing to know anything about ordnance.
    """
    target = s.place(place)
    reachable = {place, *target.adjacency}
    for force in forces:
        if force.place in reachable:
            return True
        if place in s.place(force.place).adjacency:
            return True
    return False


# --- upkeep: escalation, sustainment, supply --------------------------------


@rule(phase="upkeep")
def record_escalation(s):
    """Raise each actor's high-water rung. It never comes back down, because the
    question the chart answers is how far up this crisis went."""
    for a in s.actions:
        actor = s.actor(a.actor)
        rung = a.declared["rung"]
        if rung > actor.escalation_rung:
            s.set(actor.escalation_rung, rung)
            s.emit(
                "escalation",
                actor=a.actor,
                reason=f"reached rung {rung} with '{a.type}'",
                rung=rung,
                action=a.type,
            )


@rule(phase="upkeep")
def burn_fuel(s):
    """Charge every actor for the forces it keeps and the actions it declared.

    An actor that hits zero has every force dropped to `garrison`, whatever it
    declared. This is where a model's intent visibly loses to arithmetic, and it
    is the single most useful thing the harness shows an audience.
    """
    for actor in s.actors:
        own = s.find(owner=actor.id)
        standing = sum(BURN_RATE[f.kind] * POSTURE_BURN[f.posture] * f.strength for f in own)
        surcharge = sum(
            ACTION_FUEL_SURCHARGE.get(a.type, 0.0) * a.intensity
            for a in s.actions
            if a.actor == actor.id
        )
        spent = standing + surcharge
        had = float(actor.fuel_days)
        remaining = actor.fuel_days - spent + actor.fuel_inflow

        if remaining <= 0.0:
            s.set(actor.fuel_days, 0.0)
            grounded = [f for f in own if f.posture != "garrison"]
            for force in grounded:
                s.set(force.posture, "garrison")
            s.emit(
                "fuel_exhausted",
                actor=actor.id,
                reason=(
                    f"needed {spent:.1f} fuel-days, had {had:.1f}; "
                    f"{len(grounded)} force(s) forced to garrison"
                ),
                required=round(spent, 2),
                available=round(had, 2),
            )
        else:
            s.set(actor.fuel_days, remaining)


@rule(phase="upkeep")
def apply_supply(s):
    """Move fuel between actors. Legality already checked the supplier can pay."""
    for a in s.actions:
        if a.type != "supply" or a.target is None:
            continue
        supplier = s.actor(a.actor)
        if supplier.fuel_days < SUPPLY_TRANSFER:
            s.emit(
                "supply_failed",
                actor=a.actor,
                reason="fuel ran out before the transfer could be made",
            )
            continue
        s.transfer(supplier.fuel_days, s.actor(a.target).fuel_days, SUPPLY_TRANSFER)
        s.emit(
            "supply_delivered",
            actor=a.actor,
            reason=f"transferred {SUPPLY_TRANSFER:.0f} fuel-days to {a.target}",
            to=a.target,
            amount=SUPPLY_TRANSFER,
        )


# --- movement ---------------------------------------------------------------


@rule(phase="movement")
def apply_mobilization(s):
    """Call up reserves. Nothing appears that the scenario did not budget for."""
    for a in s.actions:
        if a.type != "mobilize":
            continue
        actor = s.actor(a.actor)
        reserve = float(actor.reserve_pool)
        called = min(REINFORCEMENT_PER_MOBILIZE * a.intensity, reserve)
        if called <= 0:
            s.emit(
                "reserves_exhausted",
                actor=a.actor,
                reason="there are no reserves left to call up",
            )
            continue
        home = [f for f in s.find(owner=a.actor) if f.kind == "ground"]
        if not home:
            s.emit(
                "reserves_exhausted",
                actor=a.actor,
                reason="no ground formation exists to absorb the reservists",
            )
            continue
        target = (
            home[0] if a.place is None else next((f for f in home if f.place == a.place), home[0])
        )
        s.add(target.strength, called)
        s.add(actor.reserve_pool, -called)
        s.emit(
            "mobilized",
            actor=a.actor,
            place=target.place,
            reason=(
                f"called up {called * TROOPS_PER_STRENGTH_POINT:,.0f} personnel; "
                f"{(reserve - called) * TROOPS_PER_STRENGTH_POINT:,.0f} remain in reserve"
            ),
            called=round(called, 2),
            remaining=round(reserve - called, 2),
        )


@rule(phase="movement")
def apply_movement(s):
    """Reposition named forces and set postures.

    A force already dropped to `garrison` by `burn_fuel` this turn stays there:
    sustainment runs first on purpose, so an actor cannot reposition on credit.
    """
    for a in s.actions:
        if s.happened("fuel_exhausted", actor=a.actor):
            continue
        if a.type == "deploy" and a.place is not None:
            for ident in a.entities:
                s.move(s.entity(ident), a.place)
            if a.entities:
                s.emit(
                    "redeployed",
                    actor=a.actor,
                    place=a.place,
                    reason=f"{len(a.entities)} force(s) moved",
                    forces=list(a.entities),
                )
        posture = POSTURE_ACTIONS.get(a.type)
        if posture is None:
            continue
        targets = [s.entity(i) for i in a.entities] if a.entities else s.find(owner=a.actor)
        for force in targets:
            s.set(force.posture, posture)


# --- contest ----------------------------------------------------------------


@rule(phase="contest")
def apply_attrition(s):
    """Resolve one Lanchester exchange per contested place.

    Square-law rather than linear: losses scale with the *opponent's* committed
    strength, which is why a four-to-one advantage is worth far more than four
    times as much. That asymmetry is the reason a weaker defender reaches for
    terrain, dispersal and irregulars instead of a stand-up fight.
    """
    for a in s.actions:
        if a.type not in OFFENSIVE_ACTIONS or a.place is None:
            continue
        region = s.place(a.place)
        attackers = [
            f for f in s.entities if f.owner == a.actor and f.kind in DELIVERY_KINDS[a.type]
        ]
        all_defenders = [f for f in s.entities if f.owner != a.actor and f.place == a.place]
        # Air defences are hunted, not slugged out with: against an air or naval
        # attacker they take suppression damage on their own schedule and stay
        # out of the exchange. Leaving them in made a battery evaporate in one
        # turn, which contradicts every published account of a SEAD campaign.
        by_air = DELIVERY_KINDS[a.type] <= frozenset({"air", "naval"})
        defenders = [f for f in all_defenders if not (by_air and f.kind == "air_defense")]
        # v1 read the air defence's strength for the divisor from a list taken
        # before suppression, so the divisor uses the strength before this turn's
        # suppression. The port keeps that.
        defence = sum(f.strength for f in all_defenders if f.kind == "air_defense") if by_air else 0
        if by_air:
            suppress_air_defense(s, a, all_defenders)
        if not attackers:
            continue
        if not defenders:
            s.emit(
                "unopposed",
                actor=a.actor,
                place=a.place,
                reason=f"'{a.type}' met no defending force",
            )
            _damage_infrastructure(s, a, region)
            continue

        attack_power = sum(_attack_power(f) for f in attackers) / _air_defence_divisor(defence)
        defend_power = sum(_attack_power(f) for f in defenders)
        intensity = a.intensity

        defender_losses = _apply_losses(s, defenders, attack_power * intensity, region)
        attacker_losses = _apply_losses(s, attackers, defend_power, region)
        s.emit(
            "exchange",
            actor=a.actor,
            place=a.place,
            reason=(
                f"{a.type} at intensity {intensity}: "
                f"attacker lost {attacker_losses:.1f}, defender lost {defender_losses:.1f}"
            ),
            attacker_losses=round(attacker_losses, 2),
            defender_losses=round(defender_losses, 2),
            attack_power=round(attack_power, 2),
            defend_power=round(defend_power, 2),
        )
        _damage_infrastructure(s, a, region)


def _attack_power(force):
    return force.strength * force.readiness * POSTURE_ATTACK[force.posture]


def _damage_divisor(force, region):
    divisor = POSTURE_DEFENSE[force.posture] * TERRAIN_DEFENSE.get(region.terrain, 1.0)
    if force.kind == "irregular" and region.terrain in ("urban", "rural"):
        divisor *= IRREGULAR_TERRAIN_BONUS
    return divisor


def _apply_losses(s, forces, incoming_power, region):
    """Spread `incoming_power` over `forces` in proportion to their strength."""
    total_strength = sum(f.strength for f in forces)
    if total_strength <= 0:
        return 0.0
    jitter = 1.0 + s.rng.uniform(-COMBAT_JITTER, COMBAT_JITTER)
    dealt = EXCHANGE_COEFFICIENT * incoming_power * jitter
    inflicted = 0.0
    for force in forces:
        strength = float(force.strength)
        share = strength / total_strength
        loss = min(strength, dealt * share / _damage_divisor(force, region))
        inflicted += loss
        s.add(force.strength, -loss)
    return inflicted


def _damage_infrastructure(s, a, region):
    if a.type not in ("strike", "air_campaign", "invade"):
        return
    damage = {"strike": 3.0, "air_campaign": 8.0, "invade": 5.0}[a.type] * a.intensity
    s.add(region.infrastructure, -damage)


def suppress_air_defense(s, a, defenders):
    """Degrade the air defences in a place under air or naval attack.

    Deterministic, with no jitter. The point of this rule is the threshold, and a
    threshold whose crossing turn wobbles by one is useless both as a teaching
    figure and as a test.
    """
    batteries = [f for f in defenders if f.kind == "air_defense"]
    if not batteries:
        return
    attackers = [f for f in s.entities if f.owner == a.actor and f.kind in DELIVERY_KINDS[a.type]]
    air_power = sum(_attack_power(f) for f in attackers)
    if air_power <= 0:
        return

    before = sum(f.strength for f in batteries)
    damage = SUPPRESSION_COEFFICIENT * air_power * a.intensity
    total = sum(f.strength for f in batteries)
    for battery in batteries:
        share = battery.strength / total if total else 0.0
        s.add(battery.strength, -(damage * share))
    after = sum(f.strength for f in batteries)

    s.emit(
        "air_defence_degraded",
        actor=a.actor,
        place=a.place,
        reason=f"air defences reduced from {before:.1f} to {after:.1f}",
        before=round(before, 2),
        after=round(after, 2),
    )
    if before >= SUPPRESSION_FLOOR > after:
        s.emit(
            "air_defence_suppressed",
            actor=a.actor,
            place=a.place,
            reason=(
                f"air defences fell below {SUPPRESSION_FLOOR:.0f}; "
                f"the airspace over {a.place} is now open"
            ),
            floor=SUPPRESSION_FLOOR,
            remaining=round(after, 2),
        )


def _air_defence_divisor(strength):
    """How much surviving air defence blunts a strike. 1.0 once suppressed."""
    if strength < SUPPRESSION_FLOOR:
        return 1.0
    return 1.0 + AIR_DEFENCE_PROTECTION * strength / 100.0


# --- consequences -----------------------------------------------------------


def occupation_requirement(population):
    """Security-force headcount needed to hold a population without an active
    insurgency. Returns the total, indigenous and external together."""
    return int(population) // INHABITANTS_PER_SECURITY_MEMBER


@rule(phase="consequences")
def decay_control(s):
    """An occupier short of the ratio loses control, and insurgents regenerate.

    This is the rule that makes taking ground different from holding it. A model
    that captures a city and then watches the number fall every turn is being
    shown, not told, why the published invasion estimates are what they are.
    """
    for region in s.places:
        occupied = bool(region.country) and region.owner not in ("", region.country)
        if not occupied or region.population <= 0:
            continue
        required = occupation_requirement(region.population)
        present = (
            sum(
                f.strength
                for f in s.entities
                if f.owner == region.owner
                and f.kind in ("ground", "irregular")
                and f.place == region.id
            )
            * TROOPS_PER_STRENGTH_POINT
        )
        if present >= required:
            continue
        shortfall = 1.0 - (present / required if required else 1.0)
        s.add(region.control, -(CONTROL_DECAY_MAX * shortfall))
        s.emit(
            "insufficient_occupation_force",
            actor=region.owner,
            place=region.id,
            reason=(
                f"holding {region.name} needs {required:,} security personnel; "
                f"{int(present):,} are present, so control is slipping"
            ),
            required=required,
            present=int(present),
            shortfall=round(shortfall, 3),
        )
        _regenerate_insurgents(s, region)


def _regenerate_insurgents(s, region):
    """Under-occupied ground grows irregulars loyal to the original owner."""
    country = str(region.country)
    if not country or country == region.owner:
        return
    existing = [
        f
        for f in s.entities
        if f.owner == country and f.kind == "irregular" and f.place == region.id
    ]
    if existing:
        s.add(existing[0].strength, INSURGENT_REGENERATION)
        return
    new_id = f"{country}-insurgents-{region.id}"
    if any(f.id == new_id for f in s.entities):
        return
    s.spawn(
        id=new_id,
        kind="irregular",
        owner=country,
        place=region.id,
        strength=INSURGENT_REGENERATION,
        readiness=0.4,
        posture="dispersed",
    )
    s.emit(
        "insurgency_formed",
        actor=country,
        place=region.id,
        reason=f"irregular resistance has appeared in {region.name}",
    )


@rule(phase="consequences")
def update_distress_and_legitimacy(s):
    """Civilian suffering, and who pays for it politically.

    The two costs run on different curves on purpose. Distress in a place costs
    the attacker international legitimacy and the place's owner domestic
    support: the same suffering is a liability for both sides, which is the
    dynamic that makes an attritional pressure campaign a race rather than a
    siege.
    """
    for region in s.places:
        if region.population <= 0:
            continue
        added = DISTRESS_PER_DAMAGE_POINT * (100.0 - region.infrastructure)
        if region.owner and s.happened("fuel_exhausted", actor=region.owner):
            added += DISTRESS_FROM_FUEL_EXHAUSTION
        if added <= 0:
            continue
        s.add(region.civilian_distress, added)

    for a in s.actions:
        if a.declared["rung"] < HARM_RUNG or a.place is None:
            continue
        region = s.place(a.place)
        if region.population <= 0:
            continue
        cost = LEGITIMACY_COST_PER_DISTRESS * region.civilian_distress
        if cost <= 0:
            continue
        s.add(s.actor(a.actor).intl_legitimacy, -cost)
        s.emit(
            "legitimacy_cost",
            actor=a.actor,
            place=a.place,
            reason=(
                f"civilian distress in {region.name} cost {a.actor} "
                f"{cost:.1f} points of international legitimacy"
            ),
            cost=round(cost, 2),
            distress=round(float(region.civilian_distress), 1),
        )

    actors = {actor.id for actor in s.actors}
    for region in s.places:
        if region.population <= 0 or not region.owner or region.owner not in actors:
            continue
        cost = SUPPORT_COST_PER_DISTRESS * region.civilian_distress
        if cost > 0:
            s.add(s.actor(region.owner).domestic_support, -cost)



def _attacked(s):
    return {a.place for a in s.actions if a.type in DAMAGING_ACTIONS and a.place}


@rule(phase="consequences")
def reconstruction(s):
    """Unattacked places rebuild toward full infrastructure."""
    attacked = _attacked(s)
    for place in s.places:
        if place.id not in attacked and place.population > 0:
            s.decay(place.infrastructure, toward=100.0, rate=RECONSTRUCTION_RATE)


@rule(phase="consequences")
def distress_eases(s):
    """Distress eases in a quiet place: not attacked this turn, and its owner not
    out of fuel. A blockade that has run a country dry keeps hurting civilians
    with nobody firing a shot, which is the pressure-campaign branch."""
    attacked = _attacked(s)
    for place in s.places:
        if place.id in attacked or place.population <= 0:
            continue
        if place.owner and s.happened("fuel_exhausted", actor=place.owner):
            continue
        s.decay(place.civilian_distress, toward=0.0, rate=DISTRESS_RELIEF_RATE)


@rule(phase="consequences")
def support_recovers(s):
    """Domestic support drifts back toward each actor's baseline."""
    for actor in s.actors:
        s.decay(actor.domestic_support, toward=actor.support_baseline, rate=SUPPORT_RECOVERY_RATE)


# --- what players are offered, and what they see ----------------------------


@offer
def available(s, actor):
    """The action types this actor could legally declare right now, each with the
    places it can reach.

    Offering an action the resolver will reject wastes a turn and teaches the
    model that its declarations are decorative. Reach is stated outright because
    a 32B model reliably fails to derive it from the map: in the first live smoke
    run one repeated an out-of-reach air campaign three turns running.
    """
    places = tuple(p.id for p in s.places)
    offered = {}
    for action_type in ACTION_TYPES:
        needed = DELIVERY_KINDS.get(action_type)
        owned = [f for f in s.find(owner=actor) if needed is None or f.kind in needed]
        if needed is not None and not owned:
            continue
        if action_type == "supply" and s.actor(actor).fuel_days < SUPPLY_TRANSFER + SUPPLY_RESERVE:
            continue
        if action_type not in PLACED:
            offered[action_type] = None
        elif needed is None:
            offered[action_type] = places
        else:
            reach = tuple(sorted(p for p in places if _can_reach(s, owned, p)))
            if reach:
                offered[action_type] = reach
    return offered


@view
def fog(s, actor):
    """What `actor` believes the world looks like.

    Own forces are exact. Everyone else's strength is scaled by a deterministic
    error whose size grows as ISR falls. A player reasoning confidently from
    wrong numbers is one of the things the harness exists to show.
    """
    isr = max(0.0, min(1.0, float(s.actor(actor).isr)))
    spread = MAX_VIEW_NOISE * (1.0 - isr)
    for force in s.entities:
        if force.owner == actor or spread == 0.0:
            continue
        sign = 1.0 if s.rng.random() < 0.5 else -1.0
        error = sign * spread * s.rng.uniform(MIN_NOISE_FRACTION, 1.0)
        s.set(force.strength, max(0.0, force.strength * (1.0 + error)))
