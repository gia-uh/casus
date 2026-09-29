---
date: 2026-09-29
status: draft, awaiting review
issue: https://github.com/gia-uh/casus/issues/5
scope: "design mode: the agent that writes a scenario, its tools, where its writes go, and how it fails"
related:
  - "docs/specs/2026-09-28-interface-design.md (the workshop screen)"
  - "docs/specs/2026-09-29-map-regions-design.md (what a place's region is)"
---

# casus — design mode

## What it is for

Writing a scenario is the expensive part of using casus. The Caribbean one took
a day: five actors with standing orders, eight places, thirteen forces, and a
source key on every place and force tying its figures to a document. Design mode lets a person get
there by asking: "add Mexico as a mediator that can only negotiate", "split
Florida in two", "what in this scenario has no source".

The agent is the second author, never the only one. Everything it writes lands
in files the person can read and edit, through the same validator a hand edit
goes through, and the workshop screen shows every call it makes.

## The runtime

A lovelaice `Agent` with a `ToolRegistry` that holds the tools below and nothing
else. There is no shell, no file access, no web beyond two tools, and the agent
never sees a filesystem path: the scenario directory is bound when the tools
are constructed, not passed as an argument.

The model is the **agent model** from settings. Tool use at this length needs a
stronger model than a player's single structured call; a local 27–32B model
works for small edits and is the fallback, not the default.

The agent's events (`AssistantMessageDelta`, `ToolExecutionStart`,
`ToolExecutionEnd`) go to the browser over a server-sent event stream, the same
mechanism the viewer uses, so the chat and its tool lines fill as they happen.

The session persists per scenario, under the user's data directory
(`~/.local/share/casus/sessions/<scenario>.jsonl`), not inside the scenario:
a scenario directory is something people copy, share and publish, and a chat
history is not part of it.

## Where writes go

A scenario directory holds the version that runs. The agent and the form write
somewhere else:

```
scenarios/<name>/
  scenario.yaml        what runs
  rules.py             what runs (absent when the scenario uses `rules: reference`)
  regions.json         computed from scenario.yaml
  sources/             archived pages and assumptions, one file per slug
  .draft/              the working copy: scenario.yaml, rules.py
```

Every write goes to `.draft/`, then the full validator runs on the draft. If it
passes, the draft replaces the files that run, `regions.json` is recomputed,
and the write returns the validation summary. If it fails, the draft stays,
the running version is untouched, and the write returns every finding.

That is the v2 design's commit moment: a failing write is kept, because a
two-step change needs its first step to survive, and a failing scenario cannot
run, because runs only ever read the validated files. The workshop's status
strip shows both: the runnable version and the draft.

The form in the workshop is a structured view of `.draft/scenario.yaml`. Saving
it is a whole-file write through the same function the agent's
`write_scenario` calls. There is one path into a scenario.

The agent and the person take turns. While the agent is working the form is
read-only, and a person's save waits until the agent's turn ends. Two writers
on one draft would make every validation result ambiguous.

## Every figure has a source, or says it is an assumption

Every actor, place and entity carries a `source` key naming a slug in
`sources/`. The Caribbean scenario already does this for its eight places and
thirteen forces, 21 keys, checked only by the class scenario's own tests. This
spec makes the validator enforce it for every scenario, and extends it to
actors, whose resources are figures too: the Caribbean scenario gains five
actor sources when it migrates.

A slug comes into `sources/` in exactly two ways:

- **`cite(url)`** fetches the page, archives it as Markdown with its URL and
  fetch date in the frontmatter, and returns the slug.
- **`assume(slug, reason)`** records an assumption: a figure chosen by
  judgement, with the reasoning, and no document behind it. The Caribbean
  scenario already has one, `estimate-from-doctrine`, and its recovery rates
  are another.

`write_scenario` rejects a `source` that names no archived slug. It does not
reject an assumption. The alternative, requiring a document for every figure,
was considered and rejected: an agent that must cite something to write a
number it had to estimate will find something to cite. Making the assumption
explicit and visible is what keeps it honest. The workshop shows assumptions
in a different colour, and `casus validate` counts them.

Coefficients in `rules.py` are not scenario data and the validator cannot see
their provenance. They keep the reference ruleset's convention: a module
constant with a comment giving its source, and the agent's instructions say so.

## The tools

Twelve. The v2 design listed eleven; `assume` is the addition, for the reason
above. `geography` is folded into `reference`, so the count of things the
agent can do stays small.

| tool | what it does | what it returns |
|---|---|---|
| `create(name)` | a new scenario from the template | the new scenario's summary |
| `read_scenario()` | the draft's `scenario.yaml` | the text |
| `write_scenario(text)` | whole file to the draft, then validate | the summary, or every finding |
| `read_rules()` | the draft's `rules.py`, or the reference's if it uses `rules: reference` | the text, and which it is |
| `write_rules(text)` | whole file to the draft, then validate | the summary, or every finding |
| `validate()` | the full validator on the draft, invariants included | findings, and the region report |
| `dry_run(turns=1)` | everyone holds for N turns | the trajectory of each displayed quantity, and invariant findings |
| `reference(what)` | read-only: the reference scenario, the reference rules, the template, or the provinces of a country | the text, or a table of ISO code and name |
| `search_sources(query)` | search this scenario's `sources/` and any source directories in settings | excerpts with their slugs |
| `search_web(query)` | DuckDuckGo | titles, URLs and snippets |
| `cite(url)` | fetch through Firecrawl, archive into `sources/` | the slug |
| `assume(slug, reason)` | record an assumption in `sources/` | the slug |

Writes are whole files, never patches. A patch makes the model reason about
line numbers and leaves half-valid states behind; regenerating a file is
something a model does well, and a whole-file write gives a clean accept or
reject.

`reference("provinces DO")` is how the agent chooses regions: it lists the
Dominican Republic's provinces with their codes, and the region block names
them. The region report in `validate` then tells it what each place came out
as, what is adjacent to what, and what went wrong.

`cite` needs a Firecrawl token. Without one it fails with that message, and the
agent can still write assumptions; the settings screen already shows the token
as *not set*.

## The agent's instructions

The system prompt is part of this spec because it carries rules the tools
cannot enforce:

- Start from `rules: reference`. Write a `rules.py` only when the person asks
  for a mechanic the reference does not have, and say which one.
- Read before writing: `read_scenario` before any `write_scenario`.
- Search before citing, cite before writing a figure, assume only when no
  source will say it, and give the reason.
- After a write passes, run `dry_run` before calling a change done, and report
  anything the invariants flag.
- Say what changed, in the scenario's language, in two or three sentences. The
  diff is on screen; the summary is for the room.

The template and the reference scenario are the agent's worked examples. It
reads them through `reference`, never from its training.

## How it fails, on purpose

- **It cannot stop failing validation.** After four consecutive writes that do
  not validate, the loop stops, and the agent reports the finding it could not
  fix and what it tried. The draft keeps its last attempt; the running version
  never saw any of them.
- **It invents a source.** It cannot: a `source` must name a slug that `cite`
  or `assume` created. What it can do is cite a real page that does not say
  what it claims. The archived page is one click away in the workshop, and
  `search_sources` returns the excerpt the figure came from, which is how a
  person checks.
- **A cited page carries instructions.** A fetched page can say "ignore your
  instructions and…". The agent has no shell and no path, and every write goes
  through the validator into a draft the person sees. The worst case is a bad
  draft on screen, not an action outside the scenario.
- **It changes more than it was asked.** Whole-file writes make this possible.
  The workshop shows a diff of every write against the previous draft, so a
  change nobody asked for is visible where it happened.
- **The model is too weak for the task.** A local model loops or writes
  malformed YAML. The failure cap stops it, and the report says which step it
  was on, which is what the person needs to decide to switch models.

## Testing

- Each tool against a temporary scenario directory, including every rejection:
  an unknown slug, a draft that fails, a failing `write_rules`.
- The commit moment: a failing write leaves the running files byte-identical;
  a passing one replaces them and recomputes `regions.json`.
- Isolation: no tool accepts a path, and a tool given `../` in a name or slug
  refuses it.
- The failure cap, with a scripted model that always writes invalid YAML.
- The form and the agent calling the same write function: a test asserts the
  form's endpoint and `write_scenario` produce identical drafts from identical
  text.
- One scripted end-to-end session per failure mode above, against lingo's mock
  model, so the loop's control flow is tested without a network.

## Out of scope

- Editing the map by dragging seeds. Seeds are numbers in the form; the map
  shows the result.
- Several people designing one scenario at once.
- An agent that runs studies. Design writes scenarios; evaluate reads runs.
