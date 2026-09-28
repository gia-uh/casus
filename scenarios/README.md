# Scenarios

A scenario is a directory:

```
scenario.yaml   actors, resources, places, entities, actions, briefings, display
rules.py        the physics, unless scenario.yaml says `rules: <name>`
```

`smoke/` exercises every call a rule can make and is not a model of anything.
`reference/` holds the reference ruleset (v1's wargame physics) and a small
public scenario that runs on it; a scenario that wants that physics writes
`rules: reference` and carries no `rules.py`.

## Private scenarios

Scenarios built for a particular class or study are not published with the
engine. They carry sourced figures about real states and belong with the people
who can read them in context.

The engine takes a path, so a private scenario needs nothing more than one:

```bash
uv run casus run /path/to/your-scenario --seed 42
```

By convention `scenarios/private/` is a link to wherever they are kept, and it is
gitignored:

```bash
ln -s ~/wherever/scenarios scenarios/private
```

The tests that check provenance — every entity and place naming a source listed
in a `SOURCES.md` beside them — run against `scenarios/private/` when it is
present and skip when it is not. That is deliberate: a scenario without
provenance should fail the suite of whoever is maintaining it, even though the
scenario itself never ships.

## Writing one

Copy `reference/` for the wargame physics or `smoke/` for a small ruleset of your
own. Every identifier is English, including resources, entity kinds, actions and
rule names; the `display.labels` block carries the scenario's language.

Run `casus validate <dir>` as you go. It reports every finding at once, each with
its reason: a direct assignment to state, an import other than `casus.ruleset`
and `math`, a rule naming a place or resource the scenario does not declare, a
rule that is not deterministic across processes, and a quantity declared
`monotone: false` that cannot actually move both ways.

Give every actor a briefing that states its objectives, its constraints and its
red lines. A briefing that lists only objectives produces a player with no
politics, which is the least interesting kind.
