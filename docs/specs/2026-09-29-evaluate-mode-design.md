---
date: 2026-09-29
status: draft, awaiting review
issue: https://github.com/gia-uh/casus/issues/5
scope: "evaluate mode: what a study is, how one grows, the agent that answers questions about it, and the rule that keeps its numbers honest"
related:
  - "docs/specs/2026-09-28-interface-design.md (the study screen)"
---

# casus — evaluate mode

## What it is for

One run of a scenario is an anecdote. The question a class should learn to ask
is what varies across runs and what comes out the same every time, and why.
On 2026-09-27 two scored runs agreed that Cuba ended with no domestic support,
and the honest reason was that nothing in the rules could raise it. The
agreement was an artifact of the physics, not a finding about the crisis, and
the mutation ledger said so to anyone who asked it.

Evaluate mode is the thing that asks. A person opens a study, reads the runs
side by side, and asks the evaluate agent questions; the agent answers from the
transcripts, and every number it states is checked against what its tools
returned.

## A study

A study is every run of **one version** of one scenario. The version is a
digest of the scenario data and the rules source, both of which every
transcript already carries in its `scenario` record. Two runs with the same
scenario name and different rules are in different studies.

The mockup got this wrong, and it is worth saying how: it put the run with the
original rules and the run with the recovery rules in one study, and the chart
showed them as two samples of one thing. They are two different models. A
comparison across versions is a legitimate question, but it is a different
question, and it is out of scope here.

The study shelf groups each scenario's versions, newest first, and labels each
with its date and what changed if the design session left a summary.

There is no new storage. A study is a query over `runs/`: read each
transcript's first record, digest it, group.

## Growing a study

**Add runs** launches a batch: N seeds (10 by default, starting after the
highest seed already in the study), for the scenario's current version. Before
it starts, the screen says how many model calls that is (runs × turns × actors,
plus a narrator call per turn) so nobody discovers the bill afterwards.

Runs go out with a concurrency limit from settings (2 by default; each run
already makes one call per actor at once). Each finished run appears in the
study as it lands. A run that fails stays in the study as failed, with its
error, and does not stop the batch.

A batch can only add runs of the current version. Running an old version would
need its files back, and the transcript is the record of that version, not a
way to restore it.

## The agent

A lovelaice `Agent` with its own `ToolRegistry`, the same runtime as design
mode: its events stream to the browser, its session persists per study under
the user's data directory, and it runs on the agent model from settings.

### It does not execute code

The v2 design gave it "compute across runs". This spec replaces that with a
fixed set of queries, each computed in Python over the transcripts:

| tool | returns |
|---|---|
| `list_runs()` | each run: id, seed, turns completed, status, the displayed quantities at the end |
| `series(quantity, holder)` | a table: turn by run, for one resource or attribute of one actor, place or entity |
| `finals(quantity, holder)` | the final value per run, with min, median and max |
| `events(id=None)` | event counts per run, and the turns each happened on |
| `ledger(ref, run)` | every mutation of one value in one run: turn, phase, rule, before, after |
| `choices(actor=None)` | action types declared per actor, counted per run and per turn |
| `read_scenario()` | the version's `scenario.yaml` |
| `read_rules()` | the version's rules source |
| `show(quantity, holder)` | switches the study's chart to that series; returns nothing the agent needs |

Arbitrary code would answer more questions, and every answer would then rest on
code nobody on screen read. A fixed query answers fewer questions, and each
answer rests on a function with tests. The first question the mode existed
for, "why does this quantity never recover", is `series`, then `ledger`, then
`read_rules`: which rules ever touched it, and that none of them can raise it.

### Its numbers must come from its tools

casus is built on one rule: the language model never computes a quantity. The
evaluate agent is the one place where a model talks about quantities at length,
so the rule applies to its prose.

After each answer, a checker extracts every number in the text and looks for it
in the results of the tools called during the session. A stated number matches
when some tool result, rounded to the precision the text used, equals it: "22"
matches 22.0075, "22,1" matches 22.13. Decimal commas, thousands separators and
percentages are normalised first.

A number with no match is marked in the chat, and the answer's footer counts
them: "2 figures not found in any query". The answer is not blocked. The mark
is information for the room, and it is often the most instructive thing on the
screen: the model rounded, or derived a difference itself, or invented.

A derived figure (a difference, a ratio) is the case the rule is strictest
about, and on purpose. If the agent wants to say "fell by 30 points", the honest
route is a query that returns 30. `finals` returns the spread; the ledger
returns each change. When a question needs a derivation none of the tools
return, that is a gap in the tools, and the fix is a new query with a test.

### It says how much it is standing on

Every claim names the runs it rests on. A study of two runs can show that
something happened; it cannot show that it always happens. The instructions
say to state the number of runs with every generalisation and to suggest
adding runs when a study is too small to separate a pattern from a seed, and
the mockup's second question ("what changes between runs and what stays the
same") already produced that answer.

## The screen

As in the interface spec: run cards, one series chart with two selectors, and
the agent pane with its tool lines. Two additions from this spec:

- the chart follows the conversation: `show` switches it, so the room sees the
  series the agent is talking about;
- unmatched figures are marked in the answer, and the footer counts them.

## Testing

- The study key: two transcripts with the same data and rules land in one
  study; changing one coefficient in the rules source splits them.
- Each query against a small recorded study built from `smoke` runs, with
  expected tables written from the transcripts, not from the query's own
  output.
- The number checker: matches at each precision, decimal comma, thousands
  separator, percentage; a derived difference is flagged; a number that
  appears only in the question, not in a tool result, is flagged.
- A scripted session, against lingo's mock model, that asks the "never
  recovers" question and must reach `ledger` and `read_rules`.
- Batches: N runs launched, the concurrency limit respected (a recorded engine
  that counts calls in flight), a failing run recorded without stopping the
  batch.

## Out of scope

- Comparing versions of a scenario. It is a real question and needs its own
  design: which differences in the rules explain which differences in the
  outcomes.
- Statistics beyond min, median and max. A class with ten runs needs to see
  spread before it needs a confidence interval.
- The agent proposing changes to the scenario. It can say what it found; a
  person takes it to design mode.
