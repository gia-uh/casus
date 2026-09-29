---
date: 2026-09-29
status: draft, awaiting review
issue: https://github.com/gia-uh/casus/issues/5
scope: "places as territory: regions built from real provinces, split by Voronoi where needed; adjacency computed from shared borders; the map data shipped in the package"
related: "docs/specs/2026-09-28-interface-design.md"
---

# casus — map regions

## What changes, and why

Today a place is a point: `lat` and `lon` among its attributes, drawn as a dot
sized by the forces on it. The room cannot see which part of Cuba "Centro" is,
or where the Straits of Florida end, and the author writes adjacency by hand as
a list per place.

After this spec a place is a territory. A place declares where its region comes
from, casus computes the polygon once, and the viewer fills it. The same
geometry gives adjacency for free: two regions are neighbours when they share a
border or a coast.

This was settled on 2026-09-28/29 by drawing the Caribbean scenario three ways
(dots, Voronoi over country outlines, real provinces grouped) and then mixed.
Alex chose provinces wherever they exist, with Voronoi where they do not.

## One rule

The **base** of a place is one of:

- the union of the **provinces** it names, by ISO 3166-2 code;
- a whole **country**, by ISO 3166-1 alpha-2 code;
- the **sea**: water inside the theatre.

If several places share the same base, they **split it by Voronoi** among their
seeds. A place alone on its base takes all of it and needs no seed.

Two more kinds cover what the rule cannot:

- a **site** is a small disc carved out of whatever region contains it: a base,
  an enclave, an airfield. A Voronoi seed for Guantánamo inside Cuba would take
  half of the eastern provinces;
- a **sea zone** is a sea place whose Voronoi cell is also cut to a maximum
  distance from its seed, so four zones do not claim the whole Gulf of Mexico.
  Water no zone reaches belongs to no place and is not in play.

```yaml
places:
  cu-habana:                       # provinces
    name: Havana
    owner: CU
    region: {provinces: [CU-03, CU-16]}
  us-fl-south:                     # a province split by seeds
    region: {provinces: [US-FL], seed: [25.77, -80.19]}
  us-fl-north:
    region: {provinces: [US-FL], seed: [28.40, -81.40]}
  ht:                              # a whole country
    region: {country: HT}
  do-south:                        # a country split by seeds
    region: {country: DO, seed: [18.48, -69.93]}
  str-florida:                     # a sea zone
    region: {sea: [24.2, -81.3], reach_km: 240}
  gtmo:                            # a site
    region: {site: [19.90, -75.13], radius_km: 15}
```

Seeds and sites are `[lat, lon]`. "Same base" means the same set of province
codes, or the same country, or the sea; two places naming `[CU-03, CU-16]` and
`[CU-16, CU-03]` share a base.

## What the validator says about regions

A region finding is a scenario finding, with its reason, like any other:

- an unknown province or country code, with the closest codes by name;
- a seed outside its own base;
- two places on one base where one has no seed;
- a region that comes out empty, or smaller than a site (two seeds too close);
- a site that falls in no region and in no water;
- a place with a region block and also `lat`/`lon` attributes that disagree
  with its region by more than its own size.

## Adjacency is computed

Two regions are adjacent when their polygons share a border longer than a
kilometre, or when a land region touches a sea zone along the coast. A site is
adjacent to the region it was carved from and to anything that region's
boundary touches within the site's radius.

The author does not write adjacency. The YAML holds only exceptions:

```yaml
  cu-occidente:
    region: {provinces: [CU-01, CU-15, CU-99]}
    adjacency: {remove: [str-florida]}     # a coast you cannot land on
  car-south:
    adjacency: {add: [gtmo]}               # a link geometry cannot see
```

A place with a plain list, `adjacency: [a, b]`, keeps working as it does today,
and the list is authoritative for that place. The validator reports where a
plain list and the geometry disagree, as a warning, so an older scenario can be
migrated one place at a time.

## Computed once, stored with the scenario

The geometry is computed when a scenario is designed, not when it is run.

`casus regions <scenario>` (and design mode, on every validated write) reads the
region blocks, builds the polygons, computes adjacency, and writes
`scenarios/<name>/regions.json`:

- one simplified polygon per place, and its label point;
- the computed adjacency, before the YAML's exceptions are applied;
- the theatre: the bounding box of every region with a margin, or
  `display.theatre: [lon0, lat0, lon1, lat1]` when the scenario sets it;
- the land outline inside the theatre, for context: countries that are no
  place are still drawn;
- a digest of the region blocks and the map data version it was built from.

`Scenario.load` reads `regions.json`, applies the exceptions, and fills each
place's adjacency, so the engine and the rules see a plain list exactly as
today. If the digest does not match the current region blocks, loading fails
and names the command that fixes it. A stale map never plays.

The transcript's `scenario` record carries the regions: polygons, label points
and the adjacency that was used. Replay needs nothing but the transcript, as it
does today, and `casus bundle` draws the map from the transcript alone.

Running a scenario, replaying one and bundling one need neither the map data
nor shapely. Only computing regions does.

## The map data ships in the package

`pip install casus` brings the map. The source is Natural Earth's Admin 1
(states and provinces) at 1:10m, public domain: 4,596 provinces, 1.3 million
coordinates, 40.7 MB of GeoJSON.

Compaction, measured on 2026-09-29:

1. **Simplify the whole coverage at once** with `shapely.coverage_simplify`,
   tolerance 0.02° (about 2 km). Simplifying each province alone would open
   gaps and overlaps along shared borders; simplifying the coverage moves each
   shared edge once. 416,369 coordinates remain, 32%.
2. **Snap to a 0.001° grid** (about 100 m) with `shapely.set_precision`, which
   keeps the coverage valid. `shapely.coverage_is_valid` holds after snapping
   at 0.02°. At 0.01° it does not, which is why the tolerance is 0.02°.
3. **Store integers, delta-encoded** per ring, as compact JSON: 3.1 MB.
4. **Compress with xz**, which the standard library reads (`lzma`): about
   1.1 MB in the wheel.

Countries are not shipped separately: a country is the union of its provinces.
Unioning Cuba, the United States and the Dominican Republic from the compacted
data gave no holes, and Havana's two provinces measure about 705 km² against
728 km² in the source.

The build is a one-shot tool, `tools/build_mapdata.py`, like
`tools/build_worldmap.py` today: it downloads the source, runs the four steps,
checks coverage validity and fails if it does not hold, and writes
`src/casus/data/admin1.json.xz`. The output is committed. The tool is not
imported.

`shapely>=2.1` becomes a dependency (`coverage_simplify` arrived in 2.1).

What 2 km means: at the Caribbean theatre, 18° wide on a 1600-pixel screen, a
pixel is about 0.012°, so the simplification sits under two pixels. A theatre
the size of one city would see it. That scenario would ship its own finer
data, and is out of scope here.

## What the viewer does with it

- Each region is filled with its owner's colour, a shade per region so
  neighbours of one owner stay distinguishable, with a light border between
  them. Sea zones are outlined, not filled.
- Entities are drawn at the region's label point, as today.
- `display.map.ring` (civilian distress, in the Caribbean) stays a small gauge
  beside the label, so the region's fill keeps meaning "who holds it".
- The whole region is the hover target for the place card.
- A scenario without region blocks draws as today: a dot per place from `lat`
  and `lon`. Nothing already recorded stops rendering.

## Testing

- The build: coverage validity after simplification and snapping; the tool
  fails when it does not hold.
- Loading the packaged data: a province round-trips to a valid polygon; a
  country union has no holes for a list of countries.
- Each region kind, on a small synthetic coverage so the test does not depend
  on real borders: provinces, a split province, a whole country, a split
  country, a sea zone with reach, a site carved out of a region.
- Adjacency: two squares sharing an edge are neighbours, two touching at a
  corner are not, a land region and a sea zone meeting at a coast are.
- Staleness: editing a region block without recomputing makes
  `Scenario.load` fail with the command to run.
- The class scenario, migrated: its computed adjacency matches its current
  hand-written lists, or every difference is listed and explained in the PR.
  That is the evidence the rule reproduces what an author decided by hand.
