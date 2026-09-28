"""The smoke scenario's rules. They exist to exercise every call a rule can make,
not to model anything."""

from casus.ruleset import offer, rule, view

RAID_DAMAGE = 5.0
RESUPPLY_AMOUNT = 5.0
REBUILD_RATE = 0.2
MILITIA_BELOW = 50.0
MILITIA_GONE_ABOVE = 55.0
VIEW_NOISE = 0.2


def _within_reach(s, actor, place):
    """A place is within reach of a unit standing in it or next to it."""
    near = {place, *s.place(place).adjacency}
    return any(e.place in near for e in s.find(owner=actor))


@rule(phase="legality", on="raid")
def raid_needs_reach(s, a):
    if not _within_reach(s, a.actor, a.place):
        s.reject(f"no unit within reach of '{a.place}'")


@rule(phase="upkeep")
def upkeep(s):
    for actor in s.actors:
        s.decay(actor.supplies, toward=0.0, rate=0.1)
    for a in s.actions:
        if a.type == "resupply":
            s.transfer(s.actor(a.actor).supplies, s.actor(a.target).supplies, RESUPPLY_AMOUNT)


@rule(phase="movement", on="deploy")
def deploy(s, a):
    for ident in a.entities:
        if s.entity(ident).owner == a.actor:
            s.move(s.entity(ident), a.place)


@rule(phase="contest", on="raid")
def raid(s, a):
    damage = RAID_DAMAGE * a.intensity * s.rng.uniform(0.9, 1.1)
    s.add(s.place(a.place).infra, -damage)
    for unit in s.find(owner=a.actor):
        s.set(unit.posture, "offensive")
    s.emit("raided", actor=a.actor, place=a.place, reason=f"infrastructure fell by {damage:.1f}")


@rule(phase="consequences")
def recovery(s):
    for p in s.places:
        if not s.happened("raided", place=p.id):
            s.decay(p.infra, toward=100.0, rate=REBUILD_RATE)
        militia = s.find(kind="militia", place=p.id)
        if p.infra < MILITIA_BELOW and not militia and p.owner:
            s.spawn(id=f"militia-{p.id}", kind="militia", owner=p.owner, place=p.id, strength=1.0)
        for m in militia:
            if p.infra > MILITIA_GONE_ABOVE:
                s.despawn(m)


@rule(phase="consequences")
def fatigue(s):
    for a in s.actions:
        if a.type == "raid":
            s.add(s.actor(a.actor).stamina, -2.0 * a.intensity)
    for actor in s.actors:
        if not s.happened("raided", actor=actor.id):
            s.add(actor.stamina, 1.0)


@offer
def available(s, actor):
    offered = {"hold": None, "deploy": tuple(p.id for p in s.places)}
    if s.actor(actor).supplies > 2 * RESUPPLY_AMOUNT:
        offered["resupply"] = None
    reachable = tuple(p.id for p in s.places if _within_reach(s, actor, p.id))
    if reachable:
        offered["raid"] = reachable
    return offered


@view
def fog(s, actor):
    for e in s.entities:
        if e.owner != actor:
            s.set(e.strength, e.strength * (1.0 + s.rng.uniform(-VIEW_NOISE, VIEW_NOISE)))
