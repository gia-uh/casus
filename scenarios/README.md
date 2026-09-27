# Scenarios

`smoke.yaml` is the shipped example: two actors, a strait, three turns. It
exercises the whole loop and is not a model of anything.

## Private scenarios

Scenarios built for a particular class or study are not published with the
engine. They carry sourced figures about real states and belong with the people
who can read them in context.

The engine takes a path, so a private scenario needs nothing more than one:

```bash
uv run casus run /path/to/your-scenario.yaml --seed 42
```

By convention `scenarios/private/` is a link to wherever they are kept, and it is
gitignored:

```bash
ln -s ~/wherever/scenarios scenarios/private
```

The tests that check provenance — every force and region naming a source listed
in a `SOURCES.md` beside it — run against `scenarios/private/` when it is
present and skip when it is not. That is deliberate: a scenario without
provenance should fail the suite of whoever is maintaining it, even though the
scenario itself never ships.

## Writing one

Copy `smoke.yaml`. The loader validates on read — unknown terrain, an adjacency
to a region that does not exist, a force owned by an actor that does not exist, a
duplicate force id, an actor with no briefing — so a typo fails at the door
rather than surfacing as a rejected action on turn four.

Give every actor a briefing that states its objectives, its constraints and its
red lines. A briefing that lists only objectives produces a player with no
politics, which is the least interesting kind.
