# Slice 4 — streaming a declaration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In a live run, each war-room pane types its actor's rationale as the model writes it, while the actions stay sealed until every actor has declared.

**Architecture:** Part A changes lingo. `LLM.create` gains `on_token`: with it, the structured request goes through the OpenAI SDK's `client.chat.completions.stream(...)` with the same `response_format`, each `content.delta` fragment goes to the callback, and `get_final_completion()` supplies the parsed model. The length-retry loop stays, and a new `on_retry(attempt)` callback tells the caller to discard the fragments it has. lingo releases this as 2.2.0. Part B is in casus. `RationaleReader` follows the growing JSON and returns only the characters of the top-level `rationale` string. `Player.decide` feeds it when given `on_rationale`, and `engine.run_async` turns those characters into `delta` messages for the observer, never for the transcript. `records.js` keeps the deltas and `viewer.js` shows them until the declaration arrives.

**Tech Stack:** lingo (Python 3.12+, openai SDK, pytest-asyncio, ruff format at its default 88 columns), casus (Python 3.12+, pytest, plain JS, Playwright).

**Specs:** `docs/specs/2026-09-28-interface-design.md`, sections "Declarations stay sealed until all are in", "Streaming a declaration", "Pacing" and "Testing". Master plan: `docs/plans/2026-09-29-casus-app-plan.md` (the contracts section is binding; this slice needs the changes listed at the end).

## What was checked before writing this

- **The OpenAI streaming API is `client.chat.completions.stream(...)`, not the `beta` namespace.** It is a plain (non-async) method that returns an `AsyncChatCompletionStreamManager`. Entering that with `async with` yields an `AsyncChatCompletionStream`, which iterates events. Content fragments are events with `type == "content.delta"` and a `delta: str` field, and `await stream.get_final_completion()` returns a `ParsedChatCompletion` whose `choices[0].message.parsed` is the model instance. Checked in both SDKs in play:
  - lingo's lock pins `openai 2.15.0`: `def stream(` at `lingo/.venv/lib/python3.12/site-packages/openai/resources/chat/completions/completions.py:2912` (`class AsyncCompletions` at 1546, with `response_format` at 2918 and `stream_options` at 2940). `async def get_final_completion` is at `openai/lib/streaming/chat/_completions.py:217`, and `class ContentDeltaEvent` (`type: Literal["content.delta"]`, `delta: str`) is at `openai/lib/streaming/chat/_events.py:18`.
  - casus's venv has `openai 3.19.2`: `def stream(` at `casus/.venv/lib/python3.13/site-packages/openai/resources/chat/completions/completions.py:3203` (`class AsyncCompletions` at 1695). `get_final_completion` is at `openai/lib/streaming/chat/_completions.py:216`, and `ContentDeltaEvent` is at `_events.py:18`.
  - `openai/resources/beta/` has no `chat` package in either version, so the beta path does not exist any more.
- **A truncated stream fails after its fragments have been delivered.** The SDK raises `LengthFinishReasonError` from inside the iteration, when the chunk carrying `finish_reason == "length"` arrives (`_completions.py:432` in 2.15.0, `:431` in 3.19.2). By then every fragment of the truncated attempt has reached `on_token`. This is why the retry has to be visible to the caller.
- **lingo's `main` is ahead of PyPI and its CI is red.** PyPI's latest is `2.1.0`. `main` carries ten unreleased commits, among them the retry (`880e3c3`, `create_attempts`), and casus's installed `lingo-ai 2.1.0` does not have it. The last "Run Tests" run on `main` failed on `ruff format --check .` for nine files (`book/tests/test_ch01.py` … `test_ch08.py`, `tests/test_llm_create_retry.py`), and the release workflow runs the same check before publishing. Task A1 fixes that first.
- **`lingo/llm.py` has drifted from `docs/llm.md`.** Commit `c8b2f61` generated `lingo/llm.py` from the literate `docs/llm.md`, and `880e3c3` then edited `lingo/llm.py` directly. Regenerating from the doc would silently drop the retry. This slice follows `880e3c3` and edits `lingo/llm.py`. It fixes the one paragraph in `docs/llm.md` that becomes false and flags the drift in the PR body. It does not regenerate anything.
- **The declaration's field order** is `actions`, `rationale`, `assessment` (`src/casus/actions.py`, `declaration_model`, the `create_model("Declaration", …)` call). While the model writes the actions, the pane therefore reads *thinking*.
- **Transcript records carry `ts`** (`engine._Transcript.write`, `record.setdefault("ts", time.time())`). The byte-identity test pins `time.time`.

## What this slice assumes from slice 3

Slice 3 is planned in parallel. This plan assumes exactly the master plan's contract and the following details of its implementation. Task B0 checks each one before any code is written:

1. `engine.run_async(..., observer: Observer | None = None)`, with `engine.Observer = Callable[[dict], Awaitable[None]]`. Every transcript record goes to `await observer(record)` after `_Transcript.write` has set its `ts`.
2. The player calls still go out through `results = await asyncio.gather(*(players[a].decide(state, *views[a]) for a in order))`.
3. `casus.server.runs.RunManager(runs_dir, engine_factory=engine_for)` calls `engine_factory(model)` once per actor and once for the narrator. `await start(scenario_dir, *, seed, turns, model)` returns the run id without waiting for the run to finish. The transcript is `runs_dir / f"{run_id}.jsonl"`, and `subscribe(run_id, after=-1)` is an async iterator that ends when the run ends. Its messages are `bundle.viewer_records` of the transcript (with `ledger`, without `mutation` or `declaration`), each carrying `"seq"`; slice 4's `delta` messages join the same numbered list.
4. `create_app(..., run_manager=None)` accepts an injected `RunManager` (slice 3's test seam). `POST /api/runs` takes `{scenario, seed, turns, model}`, where `scenario` is the directory name under `scenarios/`. `GET /api/runs/{id}/events` sends each message as `id: <seq>` plus `data: <json>`, keepalive comments, and a final `event: close`.

## Global Constraints

Everything in the master plan's Global Constraints, plus:

- `delta` messages go to the observer only. They never reach `_Transcript.write`, and a transcript is byte-identical with and without streaming.
- No partial action reaches the browser. The only thing sent while a model writes is what `RationaleReader.feed` returns.
- Streaming happens only when `run_async` has an observer. `casus run`, `casus verify` and replay behave exactly as before, and they call engines without `on_token`.
- An engine or endpoint that cannot stream still plays. The pane reads *thinking* until the declaration arrives and then shows the rationale whole.
- lingo code follows lingo's settings: ruff format at the default 88 columns, `pytest.mark.asyncio`, and `CHANGELOG.md` in Keep a Changelog form.

## Review Focus

Owned by this slice:

1. **A truncated attempt followed by a retry must not show two attempts' text run together.** Pinned by `tests/test_llm_create_stream.py::test_on_retry_separates_a_truncated_attempt_from_the_next` (lingo), `tests/test_stream.py::test_a_retried_attempt_starts_the_rationale_again`, `tests/test_stream.py::test_a_retried_attempt_is_announced_to_the_observer` and `tests/test_ui_scripts.py::test_a_reset_forgets_the_attempt_before_it`.
2. **The key `rationale` appearing inside another string, or nested below the top level, must not be read as the rationale.** Pinned by `tests/test_stream.py::test_a_key_inside_another_string_is_not_the_field` and `::test_a_field_nested_below_the_top_level_is_not_the_field`.
3. **A stream that breaks still plays.** Pinned by `tests/test_stream.py::test_a_stream_that_breaks_falls_back_to_one_plain_call` and `::test_a_run_whose_stream_breaks_still_plays`.
4. **An observer that raises must not be mistaken for an endpoint that cannot stream.** Pinned by `tests/test_stream.py::test_a_failing_observer_is_not_mistaken_for_a_broken_stream`.
5. **A subscriber that joins while deltas are flowing still gets each transcript record exactly once.** Pinned by `tests/test_server.py::test_a_subscriber_that_joins_mid_stream_gets_each_record_once`.

---

## Part A — lingo (`/home/apiad/Workspace/repos/lingo`, GitHub `gia-uh/lingo`)

lingo's own conventions apply here: conventional commits, `CHANGELOG.md` under `[Unreleased]`, ruff format at 88 columns, and tests under `tests/` with `pytest.mark.asyncio`. A release is a version bump in `pyproject.toml`, `lingo/__init__.py` and `uv.lock` with a `chore(release): …` commit, followed by a GitHub release `vX.Y.Z`. `.github/workflows/release.yaml` then runs the format check and the tests and publishes to PyPI.

### Task A1: Branch, and a green baseline

**Files:**
- Modify (formatting only): `book/tests/test_ch01.py` … `book/tests/test_ch08.py`, `tests/test_llm_create_retry.py`

**Interfaces:** none.

- [ ] **Step 1: Open the issue and the worktree**

```bash
cd /home/apiad/Workspace/repos/lingo && git fetch origin && git status --short
gh issue create -R gia-uh/lingo --title "Stream structured output: create(on_token=...)" --body-file - <<'EOF'
`LLM.create` uses the non-streaming `parse`, so a caller cannot show a structured
answer while it is being written. casus needs this to type each player's rationale
live (gia-uh/casus#5, slice 4).

Proposal: `LLM.create(model, messages, *, on_token=None, on_retry=None, **kwargs)`
and the same two keywords on `Engine.create`. With `on_token`, stream with the same
`response_format` through `client.chat.completions.stream(...)`, hand each
`content.delta` fragment to `on_token`, and return the parsed model as now.
`on_retry(attempt)` fires before every attempt after the first, because a
truncated stream has already delivered its fragments when the SDK raises
`LengthFinishReasonError`.
EOF
```

Note the issue number it prints as `<n>`. Then:

```bash
git -C /home/apiad/Workspace/repos/lingo worktree add .claude/worktrees/<n>-stream-create \
  -b <n>-stream-create origin/main
cd /home/apiad/Workspace/repos/lingo/.claude/worktrees/<n>-stream-create
uv sync --all-extras --all-groups
```

- [ ] **Step 2: Confirm main's CI failure locally**

Run: `uv run ruff format --check .; echo "rc=$?"`
Expected: `9 files would be reformatted`, `rc=1`. These are the nine files listed under Files.

- [ ] **Step 3: Format, and check both gates**

```bash
uv run ruff format .
uv run ruff format --check .; echo "rc=$?"
uv run pytest -q
```

Expected: `rc=0`, then `220 passed, 1 skipped`.

- [ ] **Step 4: Commit**

```bash
git add book/tests/test_ch01.py book/tests/test_ch02.py book/tests/test_ch03.py \
  book/tests/test_ch04.py book/tests/test_ch05.py book/tests/test_ch06.py \
  book/tests/test_ch07.py book/tests/test_ch08.py tests/test_llm_create_retry.py
git commit -m "style: ruff format the files main's CI rejects"
```

---

### Task A2: `LLM.create` streams when given `on_token`, and says when it retries

**Files:**
- Modify: `lingo/llm.py` (a module-level `_invoke`, `LLM.create`, a new `LLM._stream_parse`)
- Create: `tests/test_llm_create_stream.py`
- Modify: `CHANGELOG.md` (`[Unreleased]`)

**Interfaces:**
- Produces: `LLM.create(model, messages, *, on_token: Callable[[str], Any] | None = None, on_retry: Callable[[int], Any] | None = None, **kwargs) -> T`. Callbacks may be sync or async. `on_retry(attempt)` receives the number of the attempt about to start (2, 3, …) and fires on both paths.
- Unchanged: the instance-level `LLM(on_token=...)` still only sees `chat` output.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm_create_stream.py`:

```python
"""Unit tests for streamed structured output: `create(..., on_token=...)`.

No provider is contacted. `client.chat.completions.stream` is replaced with a
fake that behaves like the OpenAI SDK's `AsyncChatCompletionStreamManager`: an
async context manager over an async iterator of events, whose
`get_final_completion()` returns the parsed completion. The SDK raises
`LengthFinishReasonError` from inside the iteration, after the truncated
attempt's fragments were delivered, and the fake does the same, because that
is what `on_retry` exists for.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest
from lingo import LLM, Context, Engine, Message
from pydantic import BaseModel


class Answer(BaseModel):
    """A trivial structured answer."""

    value: str


def _completion(value: str | None, usage=None) -> SimpleNamespace:
    parsed = Answer(value=value) if value is not None else None
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
        usage=usage,
        model="fake",
    )


def _length_error() -> openai.LengthFinishReasonError:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="length", message=SimpleNamespace(parsed=None)
            )
        ],
        usage=None,
    )
    return openai.LengthFinishReasonError(completion=completion)  # type: ignore[arg-type]


class FakeStream:
    """One streamed attempt: its fragments, then its outcome."""

    def __init__(self, fragments, final=None, error=None):
        self.fragments = list(fragments)
        self.final = final
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._events()

    async def _events(self):
        for fragment in self.fragments:
            yield SimpleNamespace(type="content.delta", delta=fragment, snapshot="")
        # A non-content event, which create must skip.
        yield SimpleNamespace(type="chunk")
        if self.error is not None:
            raise self.error

    async def get_final_completion(self):
        return self.final


def _llm(streams=(), parses=(), **kwargs):
    llm = LLM(model="fake", api_key="none", base_url="http://localhost/v1", **kwargs)
    llm.client = MagicMock()
    stream = MagicMock(side_effect=list(streams))
    parse = AsyncMock(side_effect=list(parses))
    llm.client.chat.completions.stream = stream
    llm.client.chat.completions.parse = parse
    return llm, stream, parse


MESSAGES = [Message.user("go")]


@pytest.mark.asyncio
async def test_fragments_reach_on_token_in_order_and_the_model_is_returned():
    llm, stream, parse = _llm([FakeStream(['{"val', 'ue": "o', 'k"}'], _completion("ok"))])
    seen = []
    answer = await llm.create(Answer, MESSAGES, on_token=seen.append)
    assert answer == Answer(value="ok")
    assert seen == ['{"val', 'ue": "o', 'k"}']
    assert stream.call_count == 1
    parse.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_async_on_token_is_awaited():
    llm, _, _ = _llm([FakeStream(["a", "b"], _completion("ab"))])
    seen = []

    async def collect(fragment):
        seen.append(fragment)

    await llm.create(Answer, MESSAGES, on_token=collect)
    assert seen == ["a", "b"]


@pytest.mark.asyncio
async def test_the_stream_asks_for_the_same_format_and_for_usage():
    llm, stream, _ = _llm([FakeStream(["x"], _completion("x"))], temperature=0.2)
    await llm.create(Answer, MESSAGES, on_token=lambda _: None, seed=7)
    kwargs = stream.call_args.kwargs
    assert kwargs["response_format"] is Answer
    assert kwargs["model"] == "fake"
    assert kwargs["messages"] == [m.model_dump() for m in MESSAGES]
    assert kwargs["stream_options"] == {"include_usage": True}
    assert (kwargs["temperature"], kwargs["seed"]) == (0.2, 7)


@pytest.mark.asyncio
async def test_without_on_token_create_does_not_stream():
    llm, stream, parse = _llm(parses=[_completion("plain")])
    assert (await llm.create(Answer, MESSAGES)).value == "plain"
    stream.assert_not_called()
    assert parse.await_count == 1


@pytest.mark.asyncio
async def test_the_constructor_on_token_stays_with_chat():
    """`LLM(on_token=print)` users must not start receiving JSON from create."""
    printed = []
    llm, _, _ = _llm(
        [FakeStream(["x"], _completion("x"))],
        parses=[_completion("y")],
        on_token=printed.append,
    )
    await llm.create(Answer, MESSAGES)
    await llm.create(Answer, MESSAGES, on_token=lambda _: None)
    assert printed == []


@pytest.mark.asyncio
async def test_on_retry_separates_a_truncated_attempt_from_the_next():
    events = []
    llm, stream, _ = _llm(
        [
            FakeStream(['{"val', 'ue": "tr'], error=_length_error()),
            FakeStream(['{"value": ', '"second"}'], _completion("second")),
        ]
    )
    answer = await llm.create(
        Answer,
        MESSAGES,
        on_token=lambda t: events.append(("token", t)),
        on_retry=lambda n: events.append(("retry", n)),
    )
    assert answer.value == "second"
    assert events == [
        ("token", '{"val'),
        ("token", 'ue": "tr'),
        ("retry", 2),
        ("token", '{"value": '),
        ("token", '"second"}'),
    ]
    assert stream.call_count == 2


@pytest.mark.asyncio
async def test_on_retry_fires_on_the_non_streaming_path_too():
    retries = []
    llm, _, _ = _llm(
        parses=[_length_error(), _length_error(), _completion("third")],
        create_attempts=3,
    )
    answer = await llm.create(Answer, MESSAGES, on_retry=retries.append)
    assert answer.value == "third"
    assert retries == [2, 3]


@pytest.mark.asyncio
async def test_a_first_attempt_that_succeeds_never_calls_on_retry():
    retries = []
    llm, _, _ = _llm([FakeStream(["x"], _completion("x"))])
    await llm.create(Answer, MESSAGES, on_token=lambda _: None, on_retry=retries.append)
    assert retries == []


@pytest.mark.asyncio
async def test_exhausting_the_budget_while_streaming_raises_with_the_cause():
    llm, stream, _ = _llm(
        [
            FakeStream(["a"], error=_length_error()),
            FakeStream(["b"], error=_length_error()),
        ]
    )
    with pytest.raises(ValueError, match="token ceiling on all 2 attempts") as excinfo:
        await llm.create(Answer, MESSAGES, on_token=lambda _: None)
    assert isinstance(excinfo.value.__cause__, openai.LengthFinishReasonError)
    assert stream.call_count == 2


@pytest.mark.asyncio
async def test_other_streaming_failures_are_not_retried():
    bad = openai.BadRequestError("bad schema", response=MagicMock(), body=None)
    llm, stream, _ = _llm([bad])
    with pytest.raises(openai.BadRequestError):
        await llm.create(Answer, MESSAGES, on_token=lambda _: None)
    assert stream.call_count == 1


@pytest.mark.asyncio
async def test_an_unparseable_streamed_answer_is_not_retried():
    llm, stream, _ = _llm([FakeStream(["?"], _completion(None))])
    with pytest.raises(ValueError, match="Failed to parse"):
        await llm.create(Answer, MESSAGES, on_token=lambda _: None)
    assert stream.call_count == 1


@pytest.mark.asyncio
async def test_a_streamed_answer_reports_usage_and_the_created_object():
    messages, created = [], []
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=5, total_tokens=8)
    llm, _, _ = _llm(
        [FakeStream(["x"], _completion("x", usage))],
        on_message=messages.append,
        on_create=created.append,
    )
    await llm.create(Answer, MESSAGES, on_token=lambda _: None)
    assert messages[0].usage.total_tokens == 8
    assert created == [Answer(value="x")]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_llm_create_stream.py -q`
Expected: FAIL. Most tests error with `TypeError: ... got an unexpected keyword argument 'on_token'` reaching `parse`, or with `StopAsyncIteration` from the empty `parse` side effect. `test_without_on_token_create_does_not_stream` passes already.

- [ ] **Step 3: Implement**

In `lingo/llm.py`, add after `_read_reasoning` (the `inspect` import is already at the top):

```python
async def _invoke(callback: Callable[..., Any] | None, *args: Any) -> None:
    """Call a user callback that may be sync or async."""
    if callback is None:
        return
    result = callback(*args)
    if inspect.isawaitable(result):
        await result
```

Replace `LLM.create` (from `async def create[T: BaseModel](` to its `return result`) with:

```python
    async def create[T: BaseModel](
        self,
        model: type[T],
        messages: list["Message"],
        *,
        on_token: Callable[[str], Any] | None = None,
        on_retry: Callable[[int], Any] | None = None,
        **kwargs,
    ) -> T:
        """
        Forces the LLM to respond with a JSON object matching the Pydantic model.

        Without ``on_token`` this uses the non-streaming ``parse`` endpoint. With
        it, the same request is streamed with the same ``response_format``, each
        content fragment is handed to ``on_token`` as it arrives, and the parsed
        model is returned at the end exactly as ``parse`` returns it. The
        fragments are raw JSON text; making sense of a partial object is the
        caller's business. The instance-level ``on_token`` given to ``LLM(...)``
        stays with ``chat``. Reasoning kwargs are not forwarded because
        ``parse()`` rejects unknown fields.

        A generation that hits the token ceiling is retried, up to
        ``create_attempts`` in total. Under grammar-constrained decoding a model
        occasionally fails to close the object and runs to the cap; the failure is
        transient, and measured at roughly one call in twelve against
        ``qwen/qwen3-32b`` on OpenRouter. ``on_retry(attempt)`` is called before
        every attempt after the first, with the number of the attempt about to
        start. A streaming caller must discard the fragments it has when it
        fires: a truncated stream has delivered its fragments before the SDK
        raises, and the returned object is parsed from the fragments after the
        last ``on_retry``. Nothing else is retried: a schema the provider
        rejects, or a response it cannot parse, will fail the same way every time
        and retrying only hides it.
        """
        api_messages = [msg.model_dump() for msg in messages]
        call_kwargs = self.extra_kwargs | kwargs

        last_error: openai.LengthFinishReasonError | None = None
        for attempt in range(1, self.create_attempts + 1):
            if attempt > 1:
                await _invoke(on_retry, attempt)
            try:
                if on_token is None:
                    response = await self.client.chat.completions.parse(
                        model=self.model,  # type: ignore
                        messages=api_messages,  # type: ignore
                        response_format=model,
                        **call_kwargs,
                    )
                else:
                    response = await self._stream_parse(
                        model, api_messages, on_token, call_kwargs
                    )
            except openai.LengthFinishReasonError as exc:
                last_error = exc
                continue
            break
        else:
            raise ValueError(
                f"The model hit the token ceiling on all {self.create_attempts} attempts "
                f"without closing the object."
            ) from last_error

        result = response.choices[0].message.parsed
        if result is None:
            raise ValueError("Failed to parse the response from the model.")

        if response.usage:
            usage = Usage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )
        else:
            usage = None

        await self.on_message(Message.assistant(result.model_dump_json(), usage=usage))
        await self.on_create(result)
        return result

    async def _stream_parse(
        self,
        model: type[BaseModel],
        api_messages: list[dict],
        on_token: Callable[[str], Any],
        call_kwargs: dict[str, Any],
    ) -> Any:
        """One streamed structured attempt: every content fragment to ``on_token``,
        then the parsed completion. A generation that runs to the token ceiling
        raises ``LengthFinishReasonError`` from inside the iteration, after its
        fragments were delivered."""
        request = {"stream_options": {"include_usage": True}} | call_kwargs
        async with self.client.chat.completions.stream(
            model=self.model,  # type: ignore
            messages=api_messages,  # type: ignore
            response_format=model,
            **request,
        ) as stream:
            async for event in stream:
                if event.type == "content.delta":
                    await _invoke(on_token, event.delta)
            return await stream.get_final_completion()
```

Add to `CHANGELOG.md` under `## [Unreleased]` → `### Added`, after the retry entry:

```markdown
- `LLM.create` takes an `on_token` callback. When one is given, the structured
  request is streamed with the same `response_format` through
  `client.chat.completions.stream`, each content fragment is handed to
  `on_token` as it arrives, and the parsed model is returned at the end exactly
  as the non-streaming path returns it. The fragments are raw JSON text.
  Checked against `qwen/qwen3-32b` on OpenRouter: 438 fragments, the first
  after 1.5 seconds, the parsed result unchanged. The `on_token` given to
  `LLM(...)` still only sees `chat` output, so existing callers do not start
  receiving JSON.
- `LLM.create` takes an `on_retry(attempt)` callback, called before every
  attempt after the first with the number of the attempt about to start, on
  both paths. A truncated stream has already delivered its fragments when the
  SDK raises `LengthFinishReasonError`, so a streaming caller must discard what
  it has when `on_retry` fires; the returned object is parsed from the
  fragments after the last call.
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_llm_create_stream.py tests/test_llm_create_retry.py -q`
Expected: PASS (12 new tests, the 8 retry tests unchanged).

- [ ] **Step 5: Break it on purpose**

Delete the line `await _invoke(on_retry, attempt)` and run `uv run pytest tests/test_llm_create_stream.py -q`.
Expected: FAIL in `test_on_retry_separates_a_truncated_attempt_from_the_next` and `test_on_retry_fires_on_the_non_streaming_path_too`. Restore the line and run again. Expected: PASS.

- [ ] **Step 6: Format and commit**

```bash
uv run ruff format lingo/llm.py tests/test_llm_create_stream.py
uv run ruff format --check .; echo "rc=$?"
git add lingo/llm.py tests/test_llm_create_stream.py CHANGELOG.md
git commit -m "feat(llm): stream structured output through create(on_token=...)"
```

Expected before the commit: `rc=0`.

---

### Task A3: `Engine.create` passes both callbacks through

**Files:**
- Modify: `lingo/engine.py` (`Engine.create`, one import)
- Test: `tests/test_llm_create_stream.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `Engine.create(context, model, *instructions, on_token=None, on_retry=None) -> T`. The keywords are passed to `LLM.create` only when given, so an `LLM` subclass whose `create` predates them keeps working for callers that do not stream.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm_create_stream.py`:

```python
@pytest.mark.asyncio
async def test_the_engine_passes_both_callbacks_through():
    events = []
    llm, _, _ = _llm(
        [
            FakeStream(["a"], error=_length_error()),
            FakeStream(["b"], _completion("b")),
        ]
    )
    answer = await Engine(llm).create(
        Context([Message.user("go")]),
        Answer,
        on_token=events.append,
        on_retry=events.append,
    )
    assert answer.value == "b"
    assert events == ["a", 2, "b"]


@pytest.mark.asyncio
async def test_an_engine_call_without_callbacks_does_not_stream():
    llm, stream, parse = _llm(parses=[_completion("plain")])
    answer = await Engine(llm).create(Context([Message.user("go")]), Answer)
    assert answer.value == "plain"
    stream.assert_not_called()
    assert parse.await_count == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_llm_create_stream.py -q -k engine`
Expected: FAIL with `TypeError: Engine.create() got an unexpected keyword argument 'on_token'`.

- [ ] **Step 3: Implement**

In `lingo/engine.py`, add `from collections.abc import Callable` next to the other imports, and replace `Engine.create` with:

```python
    async def create[T: BaseModel](
        self,
        context: Context,
        model: type[T],
        *instructions: str | Message,
        on_token: Callable[[str], Any] | None = None,
        on_retry: Callable[[int], Any] | None = None,
    ) -> T:
        """
        Calls LLM to create a Pydantic model.
        (Fixes Issue #2 by removing Pydantic-to-code generation)

        ``on_token`` and ``on_retry`` go to ``LLM.create``: with ``on_token`` the
        answer is streamed as raw JSON text. They are passed only when given, so
        an LLM subclass whose ``create`` predates them keeps working.
        """
        call_messages = self._expand_content(context, *instructions)

        # Addressing Issue #2: Using a simplified prompt without code generation
        prompt_str = DEFAULT_CREATE_PROMPT.format(
            type=model.__name__,
            docs=model.__doc__ or "N/A",
            schema=model.model_json_schema(),
        )

        call_messages.append(Message.system(prompt_str))

        callbacks = {
            name: fn
            for name, fn in (("on_token", on_token), ("on_retry", on_retry))
            if fn is not None
        }
        return await self._llm.create(model, call_messages, **callbacks)
```

Add to the `CHANGELOG.md` `[Unreleased]` → `### Added` list:

```markdown
- `Engine.create` passes `on_token` and `on_retry` through to `LLM.create`,
  only when they are given.
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_llm_create_stream.py tests/test_engine.py -q`
Expected: PASS.

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format lingo/engine.py tests/test_llm_create_stream.py
uv run ruff format --check .; echo "rc=$?"
git add lingo/engine.py tests/test_llm_create_stream.py CHANGELOG.md
git commit -m "feat(engine): pass on_token and on_retry through Engine.create"
```

---

### Task A4: Check against the real endpoint, the release commit, the PR, the release

**Files:**
- Modify: `docs/llm.md` (the paragraph under "A different path for structured output")
- Modify: `CHANGELOG.md`, `pyproject.toml`, `lingo/__init__.py`, `uv.lock`

**Interfaces:**
- Produces: `lingo-ai 2.2.0` on PyPI.

- [ ] **Step 1: The streaming path against the real endpoint**

This calls the real service. It is a command a person runs, not a test.

```bash
export BASE_URL=https://openrouter.ai/api/v1
export API_KEY=$(cat ~/.config/openrouter.token)
uv run python - <<'EOF'
import asyncio

from pydantic import BaseModel

from lingo import LLM, Message


class Answer(BaseModel):
    city: str
    reason: str


async def main():
    llm = LLM(model="qwen/qwen3-32b")
    parts, retries = [], []
    result = await llm.create(
        Answer,
        [Message.user("Name one capital city and say why in one sentence.")],
        on_token=parts.append,
        on_retry=retries.append,
    )
    print(len(parts), "fragments,", len(retries), "retries")
    print(result)
    assert len(parts) > 1, "the answer arrived in one piece: nothing streamed"
    if not retries:
        assert Answer.model_validate_json("".join(parts)) == result


asyncio.run(main())
EOF
```

Expected: more than one fragment, the parsed `Answer` printed, no assertion error. If the call ends in `LengthFinishReasonError` twice (the rare double truncation), run it again.

- [ ] **Step 2: Fix the paragraph in `docs/llm.md` that is now false**

In `docs/llm.md`, replace the first paragraph under `## A different path for structured output` (it begins "`create()` uses OpenAI's `parse()` endpoint rather than the streaming `completions.create`") with:

```markdown
By default `create()` uses OpenAI's `parse()` endpoint, which blocks until the answer is complete and validates the JSON against the Pydantic schema before returning. A caller that wants to show the answer while it is being written passes `on_token`: the same request then goes through `client.chat.completions.stream(...)` with the same `response_format`, each raw JSON fragment goes to the callback, and the validated object is still what `create()` returns. A partial object is never validated or returned; the fragments are text, and making sense of them is the caller's business. Because a truncated generation is retried, `on_retry(attempt)` tells the caller to discard the fragments it already has.
```

Do not regenerate `lingo/llm.py` from `docs/llm.md`: the code block there predates `880e3c3`, and regenerating would drop the retry.

- [ ] **Step 3: The release commit**

In `CHANGELOG.md`, rename `## [Unreleased]` to `## [2.2.0] - <today, YYYY-MM-DD>` and insert a new empty `## [Unreleased]` above it. In `pyproject.toml`, set `version = "2.2.0"`. In `lingo/__init__.py`, set `__version__ = "2.2.0"` (it still says `2.0.6`, because the 2.1.0 release missed it). Then:

```bash
uv lock
uv run ruff format --check .; echo "rc=$?"
uv run pytest -q
git add docs/llm.md CHANGELOG.md pyproject.toml lingo/__init__.py uv.lock
git commit -m "chore(release): 2.2.0 — streamed structured output, retry on truncation"
```

Expected: `rc=0`, and `234 passed, 1 skipped` (220 before this branch plus the 14 new tests).

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin <n>-stream-create
gh pr create -R gia-uh/lingo --title "feat: stream structured output through create(on_token=...)" \
  --body-file - <<'EOF'
Fixes #<n>.

- `LLM.create(model, messages, *, on_token=None, on_retry=None)`: with `on_token`, the
  request goes through `client.chat.completions.stream(...)` with the same
  `response_format`; fragments go to the callback; the parsed model is returned as before.
- `on_retry(attempt)` fires before every attempt after the first, on both paths, because
  a truncated stream has delivered its fragments before the SDK raises.
- `Engine.create` passes both through, only when given.
- `style:` commit: ruff format on nine files that made main's CI red.
- Release commit for 2.2.0. It also ships the unreleased retry on truncation (880e3c3).

Known drift, not fixed here: `lingo/llm.py` was generated from `docs/llm.md` (c8b2f61),
but 880e3c3 and this PR edit the Python directly. Regenerating from the doc would drop
both. This PR only fixes the doc paragraph that became false.

Checked against the real endpoint (qwen/qwen3-32b on OpenRouter): <fragments> fragments,
parsed result equal to the joined text.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

Then stop. Alex merges on green CI.

- [ ] **Step 5: The release (after the merge, and after Alex's go: this publishes to PyPI)**

```bash
cd /home/apiad/Workspace/repos/lingo && git fetch origin
git log --oneline -1 origin/main      # the merge of the PR above
awk '/^## \[2.2.0\]/{on=1;next} /^## \[/{if(on)exit} on' CHANGELOG.md > /tmp/lingo-2.2.0-notes.md
gh release create v2.2.0 -R gia-uh/lingo --target main \
  --title "v2.2.0 — streamed structured output" --notes-file /tmp/lingo-2.2.0-notes.md
gh run list -R gia-uh/lingo --workflow release.yaml -L 1
```

Wait for that run to finish (`gh run watch <id> -R gia-uh/lingo`). Expected: `completed success`.

- [ ] **Step 6: Verify the published artifact, not the checkout**

```bash
curl -s https://pypi.org/pypi/lingo-ai/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
cd /tmp && uv run --no-project --with lingo-ai==2.2.0 python -c \
  "import inspect, lingo; print(lingo.__version__); print(inspect.signature(lingo.Engine.create))"
```

Expected: `2.2.0`, then `2.2.0`, then a signature that includes `on_token=None, on_retry=None`.

---

## Part B — casus

Work in `.claude/worktrees/5-slice-4-streaming` on branch `5-slice-4-streaming`, cut from `origin/main` after slice 3 has merged:

```bash
git -C /home/apiad/Workspace/repos/casus fetch origin
git -C /home/apiad/Workspace/repos/casus worktree add .claude/worktrees/5-slice-4-streaming \
  -b 5-slice-4-streaming origin/main
cd /home/apiad/Workspace/repos/casus/.claude/worktrees/5-slice-4-streaming && uv sync --all-extras
```

Tasks B1–B6 run on fake engines and do not wait for the lingo release. B7 does.

### Task B0: Check the slice 3 assumptions

**Files:** none (read-only).

- [ ] **Step 1: Read what slice 3 left**

```bash
grep -n "observer\|Observer" src/casus/engine.py
grep -n "asyncio.gather" -A3 src/casus/engine.py
grep -n "class RunManager\|def __init__\|async def start\|def subscribe\|engine_factory" src/casus/server/runs.py
grep -n "RunManager(\|run_manager\|def create_app" src/casus/server/app.py
grep -n "data: \|event: \|id: " src/casus/server/sse.py
```

Expected: `observer` is a parameter of `run_async`, awaited with each written record; the gather line is as quoted under "What this slice assumes"; `RunManager.__init__(self, runs_dir, engine_factory=engine_for)`; `start` is `async` and keyword-only after the directory; `create_app` takes `run_manager`; the SSE helper writes `id: `, `data: ` and a closing `event: close`.

If any of these differs, adapt the code in the task that touches it (B3 for the gather line, B4 for the manager and the app, B6 for the event stream) and note the difference in the PR body. Do not change slice 3's names.

---

### Task B1: `RationaleReader`

**Files:**
- Create: `src/casus/stream.py`
- Create: `tests/test_stream.py`

**Interfaces:**
- Produces: `stream.RationaleReader(field: str = "rationale")` with `feed(fragment: str) -> str`, exactly as in the master plan. One reader per attempt. It never raises on malformed input; a bad `\u` escape reads as U+FFFD.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stream.py`:

```python
"""Streaming a declaration: the rationale reader, the player's callbacks, and
the delta messages a live run sends to its observer."""

import json

import pytest
from scenariopaths import SCENARIOS

from casus.actions import declaration_model
from casus.scenario import Scenario
from casus.stream import RationaleReader

SMOKE = Scenario.load(SCENARIOS / "smoke")

# Accents, quotes, a backslash, a slash, a newline and a character outside the
# basic plane: every way a rationale's JSON text differs from the text itself.
TRICKY = 'Reforzar la "línea" ahora.\nEl rival cede: \\ fin/ 😀'


def _answer():
    offered = {"hold": None, "raid": ("border",), "resupply": None}
    schema = declaration_model("BLUE", offered, SMOKE)
    return schema.model_validate(
        {
            "actions": [
                {"type": "raid", "place": "border", "intensity": 3},
                {"type": "resupply", "target": "RED"},
            ],
            "rationale": TRICKY,
            "assessment": 'They will "answer" at the border.',
        }
    )


# The same declaration written four ways a model or a provider might write it.
DECLARATIONS = {
    "compact": _answer().model_dump_json(),
    "ascii-escaped": json.dumps(_answer().model_dump(), ensure_ascii=True),
    "indented": json.dumps(_answer().model_dump(), ensure_ascii=False, indent=2),
    "odd-spacing": json.dumps(_answer().model_dump(), separators=(" ,\n", " :\t")),
}

# Short enough to try every pair of cut points: escaped quotes and a backslash,
# an escaped letter, a surrogate pair, and the key inside an earlier string.
SHORT = (
    r'{"actions":[{"type":"hold","note":"\"rationale\":\"no\""}],'
    r'"rationale":"a\"b\\cé😀\n","assessment":"x"}'
)


def _fed(text: str, *cuts: int, field: str = "rationale") -> str:
    reader = RationaleReader(field)
    bounds = [0, *cuts, len(text)]
    return "".join(reader.feed(text[a:b]) for a, b in zip(bounds, bounds[1:], strict=False))


@pytest.mark.parametrize("name", sorted(DECLARATIONS))
def test_every_single_cut_yields_exactly_the_rationale(name):
    text = DECLARATIONS[name]
    expected = json.loads(text)["rationale"]
    assert expected == TRICKY
    for i in range(len(text) + 1):
        assert _fed(text, i) == expected, f"cut at {i}: {text[max(0, i - 12) : i + 12]!r}"


@pytest.mark.parametrize("name", sorted(DECLARATIONS))
def test_one_character_at_a_time_yields_exactly_the_rationale(name):
    text = DECLARATIONS[name]
    assert _fed(text, *range(1, len(text))) == TRICKY


def test_every_pair_of_cuts_in_a_short_answer_yields_exactly_the_rationale():
    expected = json.loads(SHORT)["rationale"]
    for i in range(len(SHORT) + 1):
        for j in range(i, len(SHORT) + 1):
            assert _fed(SHORT, i, j) == expected, f"cuts at {i}, {j}"


@pytest.mark.parametrize("name", sorted(DECLARATIONS))
def test_nothing_is_emitted_while_the_actions_are_written(name):
    text = DECLARATIONS[name]
    reader = RationaleReader()
    assert reader.feed(text[: text.index('"rationale"')]) == ""


def test_the_rationale_is_emitted_as_it_arrives_not_at_the_end():
    text = DECLARATIONS["compact"]
    reader = RationaleReader()
    start = text.index('"rationale"') + len('"rationale":"')
    assert reader.feed(text[:start]) == ""
    assert reader.feed(text[start : start + 8]) == TRICKY[:8]


def test_a_key_inside_another_string_is_not_the_field():
    assert _fed(SHORT) == 'a"b\\cé😀\n'


def test_a_field_nested_below_the_top_level_is_not_the_field():
    text = '{"actions":[{"rationale":"inner"}],"rationale":"outer","assessment":"x"}'
    assert _fed(text) == "outer"


def test_another_field_can_be_read():
    assert _fed(DECLARATIONS["indented"], field="assessment") == 'They will "answer" at the border.'


def test_a_malformed_escape_does_not_raise():
    assert _fed('{"rationale":"a\\uZZZZb"}') == "a�b"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_stream.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'casus.stream'`.

- [ ] **Step 3: Implement**

Create `src/casus/stream.py`:

```python
"""Reads a declaration's rationale out of JSON text as the model writes it.

lingo hands casus the raw text of a structured answer a fragment at a time. The
room should see the rationale being written and nothing else: the actions come
first in the declaration and stay sealed until every actor has declared. So this
reader follows the JSON's structure character by character and gives back only
the characters inside the top-level `rationale` string, decoded.

It is display only. lingo still parses and validates the declaration from the
whole answer, and nothing read here reaches the state.
"""

from __future__ import annotations

_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r",
            "t": "\t"}  # fmt: skip


class RationaleReader:
    """An incremental reader for one answer. Use a new one for each attempt."""

    def __init__(self, field: str = "rationale"):
        self.field = field
        self._stack: list[str] = []  # "{" or "[" for each open container
        self._expect_key = False  # inside an object, before the next member's key
        self._in_string = False
        self._is_key = False  # the open string is a key of the top-level object
        self._capture = False  # the open string is the field's value
        self._key: list[str] = []
        self._last_key: str | None = None  # the top-level key read most recently
        self._escape = ""  # "", or a partial escape: "\\", "\\u", "\\u0", ...
        self._high: int | None = None  # a high surrogate waiting for its pair

    def feed(self, fragment: str) -> str:
        """Read the next fragment; return the field's newly visible characters."""
        out: list[str] = []
        for c in fragment:
            if self._in_string:
                self._string_char(c, out)
            else:
                self._structure_char(c)
        return "".join(out)

    def _structure_char(self, c: str) -> None:
        if c == '"':
            top = len(self._stack) == 1 and self._stack[0] == "{"
            self._in_string = True
            self._is_key = top and self._expect_key
            self._capture = top and not self._expect_key and self._last_key == self.field
            self._key = []
        elif c in "{[":
            self._stack.append(c)
            self._expect_key = c == "{"
        elif c in "}]":
            if self._stack:
                self._stack.pop()
            self._expect_key = False
        elif c == ",":
            self._expect_key = bool(self._stack) and self._stack[-1] == "{"
        elif c == ":":
            self._expect_key = False
        # Whitespace, numbers, true, false and null carry nothing to show.

    def _string_char(self, c: str, out: list[str]) -> None:
        if self._escape:
            self._escape += c
            if self._escape[1] != "u":
                self._escape = ""
                self._emit(_ESCAPES.get(c, c), out)
            elif len(self._escape) == 6:
                try:
                    code = int(self._escape[2:], 16)
                except ValueError:
                    code = 0xFFFD
                self._escape = ""
                self._emit_code(code, out)
        elif c == "\\":
            self._escape = c
        elif c == '"':
            self._flush_high(out)
            if self._is_key:
                self._last_key = "".join(self._key)
            self._in_string = self._is_key = self._capture = False
        else:
            self._emit(c, out)

    def _emit_code(self, code: int, out: list[str]) -> None:
        if 0xD800 <= code < 0xDC00:
            self._flush_high(out)
            self._high = code
        elif 0xDC00 <= code < 0xE000 and self._high is not None:
            pair = 0x10000 + ((self._high - 0xD800) << 10) + (code - 0xDC00)
            self._high = None
            self._emit(chr(pair), out)
        else:
            self._emit(chr(code), out)

    def _emit(self, ch: str, out: list[str]) -> None:
        self._flush_high(out)
        if self._capture:
            out.append(ch)
        elif self._is_key:
            self._key.append(ch)

    def _flush_high(self, out: list[str]) -> None:
        """A high surrogate with no low one after it is kept as it is, which is
        what `json.loads` does."""
        if self._high is not None:
            high, self._high = self._high, None
            self._emit(chr(high), out)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_stream.py -q`
Expected: PASS (18 tests). The pair test takes about a second.

- [ ] **Step 5: Break it on purpose**

In `_structure_char`, change `top = len(self._stack) == 1 and self._stack[0] == "{"` to `top = bool(self._stack)`. Run `uv run pytest tests/test_stream.py -q`. Expected: FAIL in `test_a_field_nested_below_the_top_level_is_not_the_field` and in the `SHORT` tests. Revert.

- [ ] **Step 6: Commit**

```bash
uv run ruff check src/casus/stream.py tests/test_stream.py
git add src/casus/stream.py tests/test_stream.py
git commit -m "feat(stream): read the rationale out of a declaration as it is written"
```

---

### Task B2: `Player.decide` streams the rationale, and falls back when it cannot

**Files:**
- Modify: `src/casus/players.py`
- Modify: `tests/helpers.py` (`StreamingFakeEngine`, `with_narrator`)
- Test: `tests/test_stream.py`

**Interfaces:**
- Consumes: `RationaleReader` (B1). Streaming is used only when `engine.create` takes both `on_token` and `on_retry`, which lingo's `Engine.create` does from 2.2.0.
- Produces: `async Player.decide(self, world, prompt, offered, on_rationale: Callable[[str], Awaitable[None]] | None = None, on_restart: Callable[[], Awaitable[None]] | None = None) -> PlayerTurn`. `on_restart` is a contract change (see the end).
- `on_restart` fires (a) when lingo retries a truncated attempt and (b) when the streamed call fails and the player falls back to one plain call. An exception raised by `on_rationale` or `on_restart` propagates as itself and never triggers the fallback.
- Test helpers: `StreamingFakeEngine(reply=None, *, fragment=5, delay=0.0, truncate_first_attempt=False, broken=False)` with `.calls: list[bool]` (True for a streamed call). `with_narrator(reply)` answers the narrator too, so a fake engine can stand behind every call a live run makes.

- [ ] **Step 1: Add the test helpers**

Add `import asyncio` at the top of `tests/helpers.py`, and append:

```python
class StreamingFakeEngine(FakeEngine):
    """A FakeEngine that also streams, the way lingo's `create(on_token=...)`
    does: the answer's JSON goes to `on_token` a few characters at a time.

    `truncate_first_attempt` makes the first attempt of every call stop four
    characters into the rationale and retry, as lingo does when a generation
    hits the token ceiling. `broken` makes every streamed call fail after two
    fragments, as an endpoint that cannot stream structured output would; a
    call without `on_token` still answers.
    """

    def __init__(self, reply=None, *, fragment=5, delay=0.0, truncate_first_attempt=False,
                 broken=False):  # fmt: skip
        super().__init__(reply)
        self.fragment, self.delay = fragment, delay
        self.truncate_first_attempt, self.broken = truncate_first_attempt, broken
        self.calls: list[bool] = []

    async def create(self, context, schema, *instructions, on_token=None, on_retry=None):
        self.calls.append(on_token is not None)
        result = await super().create(context, schema, *instructions)
        if on_token is None:
            return result
        text = result.model_dump_json()
        attempts = [text]
        if self.truncate_first_attempt:
            cut = text.index('"rationale":"') + len('"rationale":"') + 4
            attempts = [text[:cut], text]
        for number, attempt in enumerate(attempts, start=1):
            if number > 1:
                await on_retry(number)
            for i in range(0, len(attempt), self.fragment):
                if self.broken and i >= 2 * self.fragment:
                    raise RuntimeError("this endpoint cannot stream structured output")
                await on_token(attempt[i : i + self.fragment])
                if self.delay:
                    await asyncio.sleep(self.delay)
        return result


def with_narrator(reply):
    """`reply` for the players, and a well-formed answer for the narrator, whose
    prompt is the one that carries the standing position."""

    def answer(prompt: str) -> dict:
        if "Standing position" not in prompt:
            return reply(prompt)
        facts = prompt.split("Standing position")[0]
        n = sum(1 for line in facts.splitlines() if line.strip()[:2].rstrip(".").isdigit())
        return {"predicates": ["acted"] * n}

    return answer
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_stream.py` (and add `import asyncio`, `import random`, `from casus.players import Player` and `from helpers import FakeEngine, StreamingFakeEngine, scripted` to its imports):

```python
RATIONALE = {"BLUE": TRICKY, "RED": "Esperar, y cuidar los suministros un día más."}
REPLIES = scripted(
    {
        "BLUE": {
            "actions": [{"type": "raid", "place": "border", "intensity": 3}],
            "rationale": RATIONALE["BLUE"],
            "assessment": "they sit tight",
        },
        "RED": {
            "actions": [{"type": "hold"}],
            "rationale": RATIONALE["RED"],
            "assessment": "a probe at the border",
        },
    }
)


def _decide(engine, actor="BLUE", **callbacks):
    player = Player(actor_id=actor, scenario=SMOKE, engine=engine)
    world = SMOKE.initial_state()
    prompt, offered = player.view(world, random.Random(1))
    return asyncio.run(player.decide(world, prompt, offered, **callbacks))


def _collector():
    """Callbacks that record the rationale handed over, with None for a restart."""
    events: list[str | None] = []

    async def on_rationale(text):
        events.append(text)

    async def on_restart():
        events.append(None)

    return events, {"on_rationale": on_rationale, "on_restart": on_restart}


def _since_restart(events) -> str:
    last = max((i for i, e in enumerate(events) if e is None), default=-1)
    return "".join(events[last + 1 :])


def test_a_player_hands_over_exactly_the_rationale_as_it_is_written():
    events, callbacks = _collector()
    turn = _decide(StreamingFakeEngine(REPLIES, fragment=3), **callbacks)
    assert None not in events
    assert len(events) > 1
    assert "".join(events) == RATIONALE["BLUE"] == turn.rationale


def test_streaming_changes_nothing_the_player_returns():
    _, callbacks = _collector()
    assert _decide(StreamingFakeEngine(REPLIES), **callbacks) == _decide(FakeEngine(REPLIES))


def test_without_on_rationale_the_engine_is_not_asked_to_stream():
    engine = StreamingFakeEngine(REPLIES)
    _decide(engine)
    assert engine.calls == [False]


def test_an_engine_that_cannot_stream_is_called_as_before():
    events, callbacks = _collector()
    turn = _decide(FakeEngine(REPLIES), **callbacks)
    assert events == []
    assert turn.rationale == RATIONALE["BLUE"]


def test_a_retried_attempt_starts_the_rationale_again():
    events, callbacks = _collector()
    _decide(StreamingFakeEngine(REPLIES, truncate_first_attempt=True), **callbacks)
    assert events.count(None) == 1
    assert "".join(events[: events.index(None)]) == RATIONALE["BLUE"][:4]
    assert _since_restart(events) == RATIONALE["BLUE"]


def test_a_stream_that_breaks_falls_back_to_one_plain_call():
    engine = StreamingFakeEngine(REPLIES, broken=True)
    events, callbacks = _collector()
    turn = _decide(engine, **callbacks)
    assert engine.calls == [True, False]
    assert events == [None]
    assert turn.rationale == RATIONALE["BLUE"]


def test_a_failing_observer_is_not_mistaken_for_a_broken_stream():
    engine = StreamingFakeEngine(REPLIES)

    async def on_rationale(text):
        raise RuntimeError("the observer broke")

    with pytest.raises(RuntimeError, match="the observer broke"):
        _decide(engine, on_rationale=on_rationale)
    assert engine.calls == [True]
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_stream.py -q -k "player or plain or observer or engine_that or retried or streaming_changes"`
Expected: FAIL with `TypeError: Player.decide() got an unexpected keyword argument 'on_rationale'`.

- [ ] **Step 4: Implement**

In `src/casus/players.py`, add to the imports:

```python
import inspect
from collections.abc import Awaitable, Callable
```

and `from .stream import RationaleReader` next to the other local imports. Add, above `class PlayerTurn`:

```python
class _CallbackFailed(Exception):
    """One of our own streaming callbacks raised. Falling back to a plain call is
    for an endpoint that cannot stream, not for a bug on this side, so the
    original exception is re-raised as itself."""


async def _ours(callback: Callable[..., Awaitable[None]], *args) -> None:
    try:
        await callback(*args)
    except Exception as exc:
        raise _CallbackFailed from exc


def _streams(engine) -> bool:
    """Whether `engine.create` takes the streaming callbacks. lingo's does from
    2.2.0; the recorded engine replay uses and the tests' plain fakes do not."""
    parameters = inspect.signature(engine.create).parameters
    return "on_token" in parameters and "on_retry" in parameters
```

Replace `Player.decide` with:

```python
    async def decide(
        self,
        world: WorldState,
        prompt: str,
        offered: Offered,
        on_rationale: Callable[[str], Awaitable[None]] | None = None,
        on_restart: Callable[[], Awaitable[None]] | None = None,
    ) -> PlayerTurn:
        """Ask the model for this actor's declaration.

        With `on_rationale` and an engine that can stream, the rationale is
        handed over as the model writes it, and `on_restart` says to forget what
        was handed over so far because the answer is being asked for again. What
        is returned is the same either way.
        """
        schema = declaration_model(self.actor_id, offered, self.scenario)
        context = Context(
            [Message.system(system_prompt(self.scenario.language())), Message.user(prompt)]
        )
        declaration = await self._declare(context, schema, on_rationale, on_restart)
        return PlayerTurn(
            actions=to_actions(declaration, self.actor_id),
            rationale=str(getattr(declaration, "rationale", "")),
            assessment=str(getattr(declaration, "assessment", "")),
            prompt=prompt,
            declaration=declaration.model_dump(),
            model=self.model,
        )

    async def _declare(self, context, schema, on_rationale, on_restart):
        if on_rationale is None or not _streams(self.engine):
            return await self.engine.create(context, schema)
        reader = RationaleReader()

        async def on_token(fragment: str) -> None:
            text = reader.feed(fragment)
            if text:
                await _ours(on_rationale, text)

        async def on_retry(attempt: int) -> None:
            nonlocal reader
            reader = RationaleReader()
            if on_restart is not None:
                await _ours(on_restart)

        try:
            return await self.engine.create(
                context, schema, on_token=on_token, on_retry=on_retry
            )
        except _CallbackFailed as failed:
            raise failed.__cause__ from None
        except Exception:
            # The endpoint could not stream this answer, or the stream broke.
            # The game does not depend on the typing: clear what the pane showed
            # and ask once more without streaming. That call's failure, if any,
            # is the one that surfaces.
            if on_restart is not None:
                await on_restart()
            return await self.engine.create(context, schema)
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_stream.py tests/test_players.py tests/test_engine.py -q`
Expected: PASS.

- [ ] **Step 6: Break it on purpose**

In `on_retry`, delete `reader = RationaleReader()`. Run `uv run pytest tests/test_stream.py -q -k retried`. Expected: FAIL. The old reader is still inside the truncated rationale string, so it reads the new attempt's opening `{"actions"…` as rationale text. Restore. Then delete the two lines `except _CallbackFailed as failed:` and `raise failed.__cause__ from None`, and run `-k failing_observer`. Expected: FAIL with `DID NOT RAISE`, because the fallback swallowed the observer's error and made a second, plain call. Restore.

- [ ] **Step 7: Commit**

```bash
uv run ruff check src/casus/players.py tests/helpers.py tests/test_stream.py
git add src/casus/players.py tests/helpers.py tests/test_stream.py
git commit -m "feat(players): hand the rationale over as the model writes it"
```

---

### Task B3: `run_async` sends `delta` messages to the observer, never to the transcript

**Files:**
- Modify: `src/casus/engine.py` (a `_streaming` helper; the `asyncio.gather` line in `run_async`)
- Test: `tests/test_stream.py`

**Interfaces:**
- Consumes: slice 3's `observer` in `run_async` and its `Observer` alias.
- Produces: `{"kind": "delta", "turn": int, "actor": str, "text": str}` per non-empty piece of rationale, and `{"kind": "delta", "turn", "actor", "text": "", "reset": True}` when a player restarts. Both go only to the observer, and only when there is one.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stream.py` (and add `from casus import engine`):

```python
def _engines(cls=StreamingFakeEngine, **kwargs):
    return {a: cls(REPLIES, **kwargs) for a in SMOKE.actors}


def _play(tmp_path, engines, name="run", observer=None, turns=2):
    out = tmp_path / f"{name}.jsonl"
    engine.run(SMOKE, seed=3, out=out, engines=engines, turns=turns, observer=observer)
    return out


def _observer():
    seen: list[dict] = []

    async def observer(record):
        seen.append(record)

    return seen, observer


def _deltas(seen, turn, actor):
    return [r for r in seen if r["kind"] == "delta" and (r["turn"], r["actor"]) == (turn, actor)]


def _shown(deltas) -> str:
    """What a viewer ends up showing: the text after the last reset."""
    last = max((i for i, d in enumerate(deltas) if d.get("reset")), default=-1)
    return "".join(d["text"] for d in deltas[last + 1 :])


def test_deltas_reach_the_observer_and_never_the_transcript(tmp_path):
    seen, observer = _observer()
    out = _play(tmp_path, _engines(), observer=observer)
    turns = sorted({r["turn"] for r in seen if r["kind"] == "prompt"})
    assert len(turns) == 2
    for turn in turns:
        for actor in SMOKE.actors:
            deltas = _deltas(seen, turn, actor)
            assert "".join(d["text"] for d in deltas) == RATIONALE[actor]
            assert all(set(d) == {"kind", "turn", "actor", "text"} for d in deltas)
    assert "delta" not in {r["kind"] for r in engine.read_records(out)}


def test_every_delta_arrives_before_its_declaration(tmp_path):
    seen, observer = _observer()
    _play(tmp_path, _engines(), observer=observer)
    for i, record in enumerate(seen):
        if record["kind"] == "declaration":
            key = (record["turn"], record["actor"])
            assert not [
                d for d in seen[i + 1 :] if d["kind"] == "delta" and (d["turn"], d["actor"]) == key
            ]


def test_a_transcript_is_byte_identical_with_and_without_streaming(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.time, "time", lambda: 1.0)
    seen, observer = _observer()
    plain = _play(tmp_path, _engines(FakeEngine), name="plain")
    quiet = _play(tmp_path, _engines(), name="quiet")
    streamed = _play(tmp_path, _engines(), name="streamed", observer=observer)
    retried = _play(
        tmp_path, _engines(truncate_first_attempt=True), name="retried", observer=observer
    )
    assert any(r["kind"] == "delta" for r in seen)
    assert streamed.read_bytes() == plain.read_bytes()
    assert quiet.read_bytes() == plain.read_bytes()
    assert retried.read_bytes() == plain.read_bytes()


def test_a_retried_attempt_is_announced_to_the_observer(tmp_path):
    seen, observer = _observer()
    _play(tmp_path, _engines(truncate_first_attempt=True), observer=observer, turns=1)
    for actor in SMOKE.actors:
        deltas = _deltas(seen, 1, actor)
        resets = [d for d in deltas if d.get("reset")]
        assert resets == [{"kind": "delta", "turn": 1, "actor": actor, "text": "", "reset": True}]
        assert _shown(deltas) == RATIONALE[actor]


def test_a_run_on_an_engine_that_cannot_stream_still_plays(tmp_path):
    seen, observer = _observer()
    out = _play(tmp_path, _engines(FakeEngine), observer=observer)
    assert not [r for r in seen if r["kind"] == "delta"]
    records = engine.read_records(out)
    assert records[-1]["kind"] == "end"
    assert {r["turn"] for r in records if r["kind"] == "action"} == {1, 2}


def test_a_run_whose_stream_breaks_still_plays(tmp_path):
    seen, observer = _observer()
    engines = _engines(broken=True)
    out = _play(tmp_path, engines, observer=observer)
    assert engine.read_records(out)[-1]["kind"] == "end"
    for actor in SMOKE.actors:
        assert engines[actor].calls == [True, False, True, False]
        assert _shown(_deltas(seen, 1, actor)) == ""


def test_without_an_observer_the_engine_is_never_asked_to_stream(tmp_path):
    engines = _engines()
    _play(tmp_path, engines)
    assert all(not any(e.calls) for e in engines.values())
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_stream.py -q -k "delta or transcript or observer or cannot_stream or breaks"`
Expected: FAIL. `test_deltas_reach_the_observer_and_never_the_transcript` finds no deltas.

- [ ] **Step 3: Implement**

In `src/casus/engine.py`, add after `engine_for`:

```python
def _streaming(observer: Observer | None, turn: int, actor: str) -> dict:
    """The callbacks that carry an actor's rationale to the observer as it is
    written. Delta messages go to the observer only, never to the transcript:
    they are how the text reached the screen, not part of what happened."""
    if observer is None:
        return {}

    async def on_rationale(text: str) -> None:
        await observer({"kind": "delta", "turn": turn, "actor": actor, "text": text})

    async def on_restart() -> None:
        await observer({"kind": "delta", "turn": turn, "actor": actor, "text": "", "reset": True})

    return {"on_rationale": on_rationale, "on_restart": on_restart}
```

In `run_async`, replace

```python
            results = await asyncio.gather(
                *(players[a].decide(state, *views[a]) for a in order)
            )
```

with

```python
            results = await asyncio.gather(
                *(
                    players[a].decide(state, *views[a], **_streaming(observer, state.turn, a))
                    for a in order
                )
            )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_stream.py tests/test_engine.py tests/test_observer.py -q`
Expected: PASS, including slice 3's `test_observer.py`.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/casus/engine.py tests/test_stream.py
git add src/casus/engine.py tests/test_stream.py
git commit -m "feat(engine): send the rationale to the observer as delta messages"
```

---

### Task B4: Deltas reach live subscribers only, and a fake engine can stand behind the app

**Files:**
- Modify (only if the new tests fail): `src/casus/server/runs.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `RunManager(runs_dir, engine_factory=...)`, `start`, `subscribe` (slice 3).
- Consumes: `create_app(*, scenarios_dir, runs_dir, settings=None, run_manager=None)` (slice 3's test seam) and `bundle.viewer_records`. Slice 3's stream carries viewer records (`ledger`, no `mutation` or `declaration`) plus a `seq` on every message, so the tests compare against `viewer_records` of the file with `seq` stripped.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server.py` (add `import asyncio`, `from casus import bundle`, `from casus.server.runs import RunManager` and `from helpers import StreamingFakeEngine, scripted, with_narrator` to its imports):

```python
LIVE_REPLIES = with_narrator(
    scripted(
        {
            "BLUE": {
                "actions": [{"type": "raid", "place": "border", "intensity": 3}],
                "rationale": "Push at the border tonight, before the other side digs in.",
                "assessment": "they will sit tight",
            }
        },
        default={
            "actions": [{"type": "hold"}],
            "rationale": "Wait, and keep the supply line quiet for one more day.",
            "assessment": "a probe at the border",
        },
    )
)


def _plain(records):
    """Stream messages without the live-only parts: deltas and sequence numbers."""
    return [{k: v for k, v in r.items() if k != "seq"} for r in records if r["kind"] != "delta"]


def _streaming_manager(runs_dir, **engine_kwargs):
    return RunManager(
        runs_dir,
        engine_factory=lambda *_, **__: StreamingFakeEngine(LIVE_REPLIES, **engine_kwargs),
    )


def test_deltas_reach_live_subscribers_and_never_the_file(tmp_path):
    manager = _streaming_manager(tmp_path, fragment=4, delay=0.001)

    async def go():
        run_id = await manager.start(SCENARIOS / "smoke", seed=1, turns=1, model=None)
        live = [r async for r in manager.subscribe(run_id)]
        late = [r async for r in manager.subscribe(run_id)]
        return run_id, live, late

    run_id, live, late = asyncio.run(go())
    on_disk = engine.read_records(tmp_path / f"{run_id}.jsonl")
    assert any(r["kind"] == "delta" for r in live)
    assert _plain(live) == bundle.viewer_records(on_disk)
    assert "delta" not in {r["kind"] for r in on_disk}
    assert _plain(late) == bundle.viewer_records(on_disk)


def test_a_subscriber_that_joins_mid_stream_gets_each_record_once(tmp_path):
    manager = _streaming_manager(tmp_path, fragment=2, delay=0.01)

    async def go():
        run_id = await manager.start(SCENARIOS / "smoke", seed=1, turns=2, model=None)
        path = tmp_path / f"{run_id}.jsonl"
        while not path.exists() or '"kind": "prompt"' not in path.read_text():
            await asyncio.sleep(0.01)
        got = [r async for r in manager.subscribe(run_id)]
        return path, got

    path, got = asyncio.run(go())
    assert any(r["kind"] == "delta" for r in got), "joined after the streaming ended"
    assert _plain(got) == bundle.viewer_records(engine.read_records(path))
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/test_server.py -q -k "deltas_reach or mid_stream"`
Expected: PASS if slice 3's fan-out publishes every observed message and skips nothing by position. If it fails, the cause is in `src/casus/server/runs.py`: any bookkeeping that counts or indexes records to decide what a subscriber has already seen must skip `kind == "delta"`, because deltas are live-only and the file never has them. Fix it there, keeping slice 3's structure, and rerun both tests and `uv run pytest tests/test_server.py -q`.

- [ ] **Step 3: A streaming engine behind the served app**

Slice 3 gave `create_app` a `run_manager` keyword for exactly this. Append to `tests/test_server.py`:

```python
def test_the_app_streams_deltas_from_an_injected_manager(tmp_path):
    client = TestClient(create_app(
        scenarios_dir=SCENARIOS, runs_dir=tmp_path,
        run_manager=_streaming_manager(tmp_path, fragment=4, delay=0.001),
    ))  # fmt: skip
    kinds = []
    with client:
        run_id = client.post("/api/runs", json={"scenario": "smoke", "seed": 1, "turns": 1,
                                                "model": None}).json()["id"]  # fmt: skip
        with client.stream("GET", f"/api/runs/{run_id}/events") as events:
            for line in events.iter_lines():
                if line.startswith("data: "):
                    kinds.append(json.loads(line[len("data: "):])["kind"])
                if '"kind": "end"' in line or '"kind":"end"' in line:
                    break
    assert "delta" in kinds and kinds[-1] == "end"
```

(Add `import json` to the imports if the file lacks it.)

- [ ] **Step 4: Run it**

Run: `uv run pytest tests/test_server.py -q -k injected_manager`
Expected: PASS. If it fails, the fault is in how `src/casus/server/runs.py` numbers or skips messages; fix it there as in Step 2.

- [ ] **Step 5: Commit**

```bash
git add tests/test_server.py src/casus/server/runs.py
git commit -m "test(server): deltas reach live subscribers only, through the served app"
```

(`git add` of an unchanged path is a no-op. Name only the paths this task touched.)

---

### Task B5: The viewer shows the deltas (`records.js`, `viewer.js`)

**Files:**
- Modify: `ui/js/records.js` (the `delta` case)
- Modify: `ui/js/viewer.js` (`rationaleFor`, `paneFrame`)
- Modify: `tests/js/harness.js`
- Test: `tests/test_ui_scripts.py`

**Interfaces:**
- Produces: `Casus.viewer.rationaleFor(run, turn, actorId, declared)`, which returns `declared.rationale` when the declaration is in and otherwise `run.deltas[turn][actorId]` joined (or `""`). `RunModel.push` of a delta with `reset: true` empties that actor's list for that turn.
- Behaviour: live, a pane shows the text that has arrived, as it arrives (no seeded typing). It reads *thinking* with no text and no declaration, *writing* with text and no declaration, and *ready* with the declaration. Recorded runs keep the seeded speed. `paneFrame` never touches `.chips`, which only `reveal()` fills at the declaring beat.

- [ ] **Step 1: Write the failing tests**

In `tests/js/harness.js`, after the `if (input.card) {...}` block and before `process.stdout.write`, add:

```js
if (input.rationale) {
  out.rationale = input.rationale.map(([turn, actor]) => {
    const t = run.turn(turn);
    const d = t ? Casus.records.declarations(t).find((x) => x.actor === actor) || null : null;
    return Casus.viewer.rationaleFor(run, turn, actor, d);
  });
}
```

Append to `tests/test_ui_scripts.py`:

```python
def _rationale(records, asks):
    payload = json.dumps({"records": records, "labels": [], "rationale": asks})
    done = subprocess.run(
        [NODE, str(HARNESS), "i18n.js,records.js,map.js,card.js,viewer.js"],
        input=payload, capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["rationale"]


def _before_the_declarations(records):
    """What a live viewer holds while the models are still writing."""
    return records[: next(i for i, r in enumerate(records) if r["kind"] == "action")]


def _delta(text, actor="BLUE", turn=1, **extra):
    return {"kind": "delta", "turn": turn, "actor": actor, "text": text, **extra}


def test_a_pane_shows_the_streamed_rationale_until_the_declaration_is_in(tmp_path):
    records = _before_the_declarations(_records(tmp_path, turns=1))
    deltas = [_delta("Push "), _delta("at the "), _delta("border")]
    assert _rationale(records + deltas, [[1, "BLUE"], [1, "RED"]]) == ["Push at the border", ""]


def test_the_declared_rationale_replaces_the_streamed_text(tmp_path):
    records = _records(tmp_path, turns=1)
    first = next(i for i, r in enumerate(records) if r["kind"] == "action")
    declared = next(r["rationale"] for r in records if r["kind"] == "action" and r["actor"] == "BLUE")
    streamed = records[:first] + [_delta("half a thou")] + records[first:]
    assert _rationale(streamed, [[1, "BLUE"]]) == [declared]


def test_a_reset_forgets_the_attempt_before_it(tmp_path):
    records = _before_the_declarations(_records(tmp_path, turns=1))
    deltas = [_delta("Refo"), _delta("", reset=True), _delta("Reforzar")]
    assert _rationale(records + deltas, [[1, "BLUE"]]) == ["Reforzar"]


def test_deltas_do_not_make_a_turn_playable(tmp_path):
    records = _records(tmp_path, turns=1)
    assert _model(records + [_delta("x", turn=9)])["playable"] == _model(records)["playable"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ui_scripts.py -q -k "streamed or declared_rationale or reset or playable"`
Expected: FAIL. `test_a_pane_shows_the_streamed_rationale...` gets `["", ""]`, and `test_a_reset_forgets...` gets `[""]`. `test_deltas_do_not_make_a_turn_playable` already passes: `records.js` never creates a turn for a delta.

- [ ] **Step 3: Implement `records.js`**

Replace the `case "delta": {...}` block in `ui/js/records.js` with:

```js
        case "delta": {
          // Live only, never in a transcript. A reset means the model is being
          // asked again, so the text so far belongs to an abandoned attempt.
          const byActor = (this.deltas[r.turn] = this.deltas[r.turn] || {});
          if (r.reset) byActor[r.actor] = [];
          else (byActor[r.actor] = byActor[r.actor] || []).push(r.text);
          break;
        }
```

- [ ] **Step 4: Implement `viewer.js`**

Replace the one-line `function rationaleFor(...)` with:

```js
  // What a pane shows: the declared rationale once the declaration is in; before
  // that, on a live run, the fragments that have streamed so far. Deltas never
  // reach a transcript, so a recorded run only ever has the first.
  function rationaleFor(run, turn, actorId, declared) {
    if (declared) return declared.rationale;
    const parts = ((run.deltas || {})[turn] || {})[actorId];
    return parts ? parts.join("") : "";
  }
```

Replace `function paneFrame() {...}` with the version below. If slice 3 changed `paneFrame` (`git log -p -- ui/js/viewer.js`), carry its changes into this version and keep the three properties the comments name.

```js
    function paneFrame() {
      let done = 0;
      const declared = C.records.declarations(T());
      for (const p of V.panes) {
        const el = document.getElementById("pane-" + p.id); if (!el) continue;
        // Live, a declaration lands after the pane was drawn. Pick it up here so
        // reveal() and the assessment see it; its actions stay out of the pane
        // until reveal() opens every pane at once.
        p.d = declared.find((x) => x.actor === p.id) || null;
        const txt = rationaleFor(run, T().turn, p.id, p.d) || "";
        // Live, the text is what has arrived, as fast as it arrives. Recorded, it
        // is typed at the pane's seeded speed.
        const n = live ? txt.length
          : V.clock < p.start ? 0 : Math.min(txt.length, Math.floor(((V.clock - p.start) / 1000) * p.cps));
        const st = el.querySelector(".status");
        if (!p.d && !live) { st.textContent = "—"; done++; continue; }
        const waiting = live ? !p.d && !txt.length : V.clock < p.start;
        const finished = !!p.d && n >= txt.length;
        if (waiting) { st.textContent = t("thinking") + ".".repeat(1 + (Math.floor(V.clock / 400) % 3)); st.className = "status"; el.classList.remove("writing"); }
        else if (!finished) { st.textContent = t("writing"); st.className = "status"; el.classList.add("writing"); }
        else { st.textContent = "✓ " + t("ready"); st.className = "status done"; el.classList.remove("writing"); done++; }
        const tx = el.querySelector(".text");
        tx.innerHTML = esc(txt.slice(0, n)) + (n > 0 && !finished ? '<span class="cur"></span>' : "");
        tx.scrollTop = tx.scrollHeight;
        const em = el.querySelector(".assess em");
        if (em && p.d && em.textContent !== p.d.assessment) em.textContent = p.d.assessment;
      }
      $("#vready").innerHTML = `<b>${pad2(done)}</b> / ${pad2(V.panes.length)} ${t("ready_count")}`;
      return done === V.panes.length;
    }
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_ui_scripts.py -q`
Expected: PASS, including every `test_every_ui_script_parses[...]` case.

- [ ] **Step 6: Commit**

```bash
git add ui/js/records.js ui/js/viewer.js tests/js/harness.js tests/test_ui_scripts.py
git commit -m "feat(ui): panes show the rationale as it streams, sealed actions until the reveal"
```

---

### Task B6: A live run in Chromium types before any action exists

**Files:**
- Test: `tests/browser/test_viewer.py`

**Interfaces:**
- Consumes: `serve(runs_dir, **app_kwargs)` (slice 1), `create_app(..., run_manager=...)` (slice 3), `POST /api/runs` and `GET /api/runs/{id}/events` (slice 3), `Casus.records.RunModel` and `Casus.viewer.mount(..., {mode: "live"})` (slice 1).
- The test mounts the live viewer itself on an `EventSource`, so it depends only on master-plan contracts and not on how slice 3's route draws its form.

- [ ] **Step 1: Write the tests**

Add to the imports of `tests/browser/test_viewer.py`: `import asyncio`, `serve` in the `browser_support` import, and `from helpers import FakeEngine, StreamingFakeEngine, scripted, with_narrator`. Append:

```python
BLUE_SAYS = "Push at the border tonight, before the other side digs in."
RED_SAYS = "Wait, and keep the supply line quiet for one more day."
LIVE_REPLIES = with_narrator(
    scripted(
        {
            "BLUE": {
                "actions": [{"type": "raid", "place": "border", "intensity": 3}],
                "rationale": BLUE_SAYS,
                "assessment": "they will sit tight",
            }
        },
        default={
            "actions": [{"type": "hold"}],
            "rationale": RED_SAYS,
            "assessment": "a probe at the border",
        },
    )
)
# What the chips would show. None of it may be in a pane before the reveal.
ACTION_WORDS = ["raid", "hold", "×"]

LIVE = """async (body) => {
  const r = await fetch("/api/runs", {method: "POST",
    headers: {"content-type": "application/json"}, body: JSON.stringify(body)});
  const {id} = await r.json();
  const run = new Casus.records.RunModel();
  window.__run = run;
  const es = new EventSource("/api/runs/" + encodeURIComponent(id) + "/events");
  es.onmessage = (e) => {
    const rec = JSON.parse(e.data);
    run.push(rec);
    if (rec.kind === "end" || rec.kind === "error") es.close();
  };
  es.onerror = () => es.close();
  const view = document.getElementById("view");
  view.innerHTML = "";
  Casus.viewer.mount(view, run, {mode: "live"});
  return id;
}"""

# Samples the war room every frame until the declarations open, in one call, so
# the check and the moment it describes cannot drift apart.
WATCH = """(forbidden) => new Promise((resolve) => {
  const seen = {textBeforeActions: "", violations: []};
  const t0 = performance.now();
  const tick = () => {
    const panes = [...document.querySelectorAll(".pane")];
    const chips = document.querySelectorAll(".pane .chip").length;
    const turn = window.__run && window.__run.turn(1);
    const actions = turn ? turn.actions.length : 0;
    const text = panes.map((p) => p.querySelector(".text").textContent).join("");
    if (chips === 0) {
      const shown = panes.map((p) => p.innerText.toLowerCase()).join("\\n");
      for (const w of forbidden) if (shown.includes(w)) seen.violations.push(w);
      if (!actions && text.length && !seen.textBeforeActions) seen.textBeforeActions = text;
    }
    if (chips > 0 || performance.now() - t0 > 30000) {
      seen.chips = chips;
      seen.final = panes.map((p) => p.querySelector(".text").textContent);
      seen.violations = [...new Set(seen.violations)];
      resolve(seen);
    } else requestAnimationFrame(tick);
  };
  tick();
})"""


def _live(page, tmp_path, engine_factory):
    from casus.server.runs import RunManager

    runs = tmp_path / "runs"
    runs.mkdir()
    url, stop = serve(runs, run_manager=RunManager(runs, engine_factory=engine_factory))
    page.goto(url)
    page.wait_for_selector("[data-scenario]")
    page.evaluate(LIVE, {"scenario": "smoke", "seed": 1, "turns": 1, "model": None})
    return stop


def test_live_panes_type_the_rationale_before_any_action_exists(page, tmp_path):
    stop = _live(page, tmp_path, lambda *_, **__: StreamingFakeEngine(
        LIVE_REPLIES, fragment=3, delay=0.05))  # fmt: skip
    try:
        seen = page.evaluate(WATCH, ACTION_WORDS)
    finally:
        stop()
    assert seen["textBeforeActions"], "no rationale reached a pane before the declarations"
    assert seen["violations"] == [], f"action words in a pane before the reveal: {seen}"
    assert seen["chips"] > 0, "the declarations never opened"
    assert sorted(seen["final"]) == sorted([BLUE_SAYS, RED_SAYS])


class _SlowPlainEngine(FakeEngine):
    """An engine that cannot stream and takes its time, like an endpoint without
    streamed structured output."""

    async def create(self, context, schema, *instructions):
        await asyncio.sleep(1.5)
        return await super().create(context, schema, *instructions)


def test_a_live_run_without_streaming_reads_thinking_then_the_whole_rationale(page, tmp_path):
    stop = _live(page, tmp_path, lambda *_, **__: _SlowPlainEngine(LIVE_REPLIES))
    try:
        page.wait_for_selector(".pane .status")
        assert page.locator(".pane .status").first.inner_text().startswith("thinking")
        assert page.locator(".pane .text").first.inner_text() == ""
        page.wait_for_function("document.querySelectorAll('.pane .status.done').length === 2")
        texts = page.locator(".pane .text").all_inner_texts()
    finally:
        stop()
    assert sorted(texts) == sorted([BLUE_SAYS, RED_SAYS])
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/browser/test_viewer.py -q -k "live_panes or without_streaming"`
Expected: PASS (both). If `.pane .status` shows `—`, the viewer was mounted in recorded mode. If `textBeforeActions` is empty, the deltas are not reaching the page: check B4 first.

- [ ] **Step 3: Break it on purpose**

In `ui/js/viewer.js`, change the first line of `rationaleFor`'s body to `return declared ? declared.rationale : "";`, so deltas are ignored. Run the first test. Expected: FAIL on `textBeforeActions`. Revert. Then, in `paneFrame`, add `if (p.d) el.querySelector(".chips").textContent = p.d.actions.map((a) => a.type).join(" ");` right after `p.d = ...`, which leaks the actions as soon as they exist. Run again. Expected: FAIL on `violations`. Revert, and run both tests once more. Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/browser/test_viewer.py
git commit -m "test(browser): live panes type before any action exists, and fall back to thinking"
```

---

### Task B7: casus depends on lingo 2.2.0 (after the release)

**Files:**
- Modify: `pyproject.toml`, `uv.lock`
- Test: `tests/test_stream.py`

**Interfaces:**
- Consumes: `lingo-ai>=2.2.0`, with `Engine.create(..., on_token=None, on_retry=None)`.

- [ ] **Step 1: Write the failing test**

This one goes through the real lingo `Engine` and `LLM`, with only the OpenAI client faked. It checks that the chain from `Player.decide` to lingo streams, which the fake engines above cannot. Append to `tests/test_stream.py` (add `from types import SimpleNamespace` and `from unittest.mock import MagicMock`):

```python
class _OpenAIStream:
    """What the OpenAI SDK's `chat.completions.stream(...)` hands lingo."""

    def __init__(self, text, schema):
        self.text, self.schema = text, schema

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._events()

    async def _events(self):
        for i in range(0, len(self.text), 7):
            yield SimpleNamespace(type="content.delta", delta=self.text[i : i + 7])

    async def get_final_completion(self):
        parsed = self.schema.model_validate_json(self.text)
        message = SimpleNamespace(parsed=parsed)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def test_a_real_lingo_engine_streams_the_rationale_to_the_player():
    from lingo import LLM, Engine

    text = json.dumps(
        {"actions": [{"type": "hold"}], "rationale": TRICKY, "assessment": "calm"},
        ensure_ascii=True,
    )
    llm = LLM(model="fake", api_key="none", base_url="http://localhost/v1")
    llm.client = MagicMock()
    llm.client.chat.completions.stream = lambda **kw: _OpenAIStream(text, kw["response_format"])
    events, callbacks = _collector()
    turn = _decide(Engine(llm), **callbacks)
    assert "".join(events) == TRICKY == turn.rationale
    assert len(events) > 1
```

- [ ] **Step 2: Run to verify failure on lingo 2.1.0**

Run: `uv run pytest tests/test_stream.py -q -k real_lingo`
Expected: FAIL. With lingo 2.1.0, `_streams` is false, so the player calls `parse` on the `MagicMock` client, which cannot be awaited.

- [ ] **Step 3: Bump lingo**

```bash
uv add "lingo-ai>=2.2.0"
uv sync --all-extras
uv run python -c "import inspect, lingo; print(lingo.__version__, inspect.signature(lingo.Engine.create))"
```

Expected: `2.2.0`, and a signature that includes `on_token=None, on_retry=None`.

- [ ] **Step 4: Run the suites this touches**

Run: `uv run pytest tests/test_stream.py tests/test_players.py tests/test_engine.py tests/test_narrator.py tests/test_server.py -q`
Expected: PASS. A lingo bump reaches every model call, so also run the rest once here: `uv run pytest -q --ignore=tests/browser`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/test_stream.py
git commit -m "build: lingo-ai 2.2.0, which streams structured output"
```

---

### Task B8: Docs, spec status, and the acceptance check against the real endpoint

**Files:**
- Modify: `README.md` (module table), `DESIGN.md` ("Transcript and replay"), `docs/specs/2026-09-28-interface-design.md` (status header), `docs/plans/2026-09-29-casus-app-plan.md` (the contract changes below, and the slice table's PR number)

- [ ] **Step 1: README**

Add a row to the module table after `players.py`:

```markdown
| `stream.py` | Reads a declaration's rationale out of the model's JSON as it is written, for the live panes |
```

- [ ] **Step 2: DESIGN.md**

Append to "Transcript and replay":

```markdown
A live run also shows each actor's rationale as the model writes it. lingo streams
the structured answer, `stream.py` reads the characters of the top-level
`rationale` string out of it, and `run_async` passes them to its observer as
`delta` messages. They never reach the transcript: they are how the text reached
the screen, not part of what happened, and a test holds the transcript
byte-identical with and without them. The reader drops everything else in the
answer, so no part of an action reaches the browser before every actor has
declared. When lingo retries a truncated answer, or an endpoint cannot stream,
the player tells the viewer to forget the text so far. In the second case it asks
once more without streaming, and the pane waits for the whole declaration. A
failed streamed attempt is not recorded, the same as a truncated attempt that
lingo retries.
```

- [ ] **Step 3: The contract changes, in the master plan**

Apply every item of "Contract changes needed" below to `docs/plans/2026-09-29-casus-app-plan.md`, in its "Contracts" and "File structure" sections, and set slice 4's row in the slice table to this PR's number.

- [ ] **Step 4: Spec status**

In `docs/specs/2026-09-28-interface-design.md`'s frontmatter `status`, add `4 (PR #<n>)` to the list of implemented slices and drop 4 from the pending ones.

- [ ] **Step 5: Acceptance, the way a person does it**

This calls the real service. Do it from the app, on the laptop:

```bash
export BASE_URL=https://openrouter.ai/api/v1
export API_KEY=$(cat ~/.config/openrouter.token)
uv run casus serve
```

In the browser, press **Run** on `smoke`, with seed 7, 1 turn and model `qwen/qwen3-32b`. Watch the war room:

1. Each pane reads *thinking* first, then *writing…* with text growing in bursts as fragments arrive. Different panes finish at different times.
2. The chip area reads `DECLARATION SEALED` until every pane is *ready*. The chips then open together at the declaring beat.
3. Hovering a place during the thinking beat says the declarations are still sealed.

Then check the file the run wrote:

```bash
ls -t runs/ | head -1                                   # the run id, e.g. smoke-7
grep -c '"kind": "delta"' runs/smoke-7.jsonl            # expect 0
uv run casus verify runs/smoke-7.jsonl                  # expect success
jq -r 'select(.kind=="action") | [.actor, .rationale] | @tsv' runs/smoke-7.jsonl | sort -u
```

The rationale each pane showed at the reveal must match that actor's line. Repeat once on `reference` with 2 turns, so five panes stream at once on a scenario with a map. In the PR body, write what was checked, on which runs, and anything that was not checked.

- [ ] **Step 6: Commit and open the PR**

```bash
git add README.md DESIGN.md docs/specs/2026-09-28-interface-design.md docs/plans/2026-09-29-casus-app-plan.md
git commit -m "docs: streaming a declaration, and the contract changes it needed"
git push -u origin 5-slice-4-streaming
gh pr create --title "feat: live panes type each rationale as the model writes it" --body "Part of #5. ..."
```

The master plan's "After each slice" list applies: a workspace journal entry for the commits and the milestone.

---

## Contract changes needed

> Applied during plan review (2026-09-29) to the master plan's "Amendments from the slice plans" section, resolved against the other slices. Do not edit the master plan again for these; if the code must differ from the amendments, change the amendments in this slice's PR.

These change names or shapes that the master plan fixes. The master plan's own rule is that they land in it in the same PR as this slice (Task B8, Step 3):

1. **`Player.decide` gains a second callback.**
   `async def Player.decide(self, world, prompt, offered, on_rationale: Callable[[str], Awaitable[None]] | None = None, on_restart: Callable[[], Awaitable[None]] | None = None)`.
   `on_restart` means "forget the rationale handed over so far". It fires when lingo retries a truncated attempt (a truncated stream has already delivered its fragments when the SDK raises `LengthFinishReasonError`), and when the streamed call fails and the player falls back to one plain call. Without it, the reader would concatenate two attempts' text.
2. **The `delta` message gains an optional `reset` key.**
   `{"kind": "delta", "turn": 3, "actor": "CU", "text": "", "reset": true}` tells the viewer to drop that actor's deltas for that turn. Like every delta, it travels over the live event stream only and is never written to a transcript.
3. **`ui/js/records.js` is modified by slice 4**, because the `delta` case honours `reset`. File structure row: `js/records.js 1: RunModel;  4: delta reset`.
4. **No new `create_app` keyword.** Tests put a streaming fake engine behind the served app through slice 3's `run_manager` seam: `create_app(..., run_manager=RunManager(runs_dir, engine_factory=...))`.
5. **File structure rows for the tests this slice touches:** `tests/helpers.py 4: StreamingFakeEngine, with_narrator`, `tests/test_server.py 1, 3, 4, 5, 6, 7 add tests`, `tests/test_ui_scripts.py 1, 4` and `tests/js/harness.js 1, 4`.
6. **The lingo floor.** The Tech Stack line reads `lingo-ai>=2.2.0`. lingo 2.2.0's API is `LLM.create(model, messages, *, on_token=None, on_retry=None, **kwargs)` and `Engine.create(context, model, *instructions, on_token=None, on_retry=None)`. This is not a new dependency, so the Global Constraints line on new core dependencies is unchanged.
