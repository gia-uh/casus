"""Real Chromium over the real viewer. Skips when Playwright or its browser is
missing, so a laptop without them still runs `make test`. Under CI (the `CI`
variable GitHub Actions sets) the same cases fail, so the gate cannot pass by
skipping itself."""

from __future__ import annotations

import json
import os

import pytest
from browser_support import run_records, serve, write_run

from casus import bundle

try:
    import playwright.sync_api as playwright_sync
except ImportError as exc:  # reported by the `browser` fixture, so it can fail in CI
    playwright_sync, missing = None, exc


def _unavailable(reason: str) -> None:
    if os.environ.get("CI"):
        pytest.fail(f"browser suite cannot run in CI: {reason}", pytrace=False)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def browser():
    if playwright_sync is None:
        _unavailable(f"playwright is not installed: {missing}")
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except playwright_sync.Error as exc:  # not installed, or installed but broken
            _unavailable(f"chromium cannot launch: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1600, "height": 900})
    pg = ctx.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
    yield pg
    ctx.close()
    assert not errors, errors


@pytest.fixture
def bundle_url(tmp_path):
    def make(records: list[dict]) -> str:
        src = tmp_path / "in.jsonl"
        src.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return bundle.bundle(src, tmp_path / "out.html").as_uri()

    return make


@pytest.fixture
def app_url(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    write_run(runs, "reference-1", run_records(tmp_path))
    url, stop = serve(runs)
    yield url
    stop()
