"""Helpers the browser tests share. Not a conftest, so it can be imported."""

from __future__ import annotations

import concurrent.futures
import json
import pathlib
import socket
import threading
import time

from casus import engine
from casus.scenario import Scenario
from helpers import FakeEngine

ROOT = pathlib.Path(__file__).parent.parent.parent


def run_records(
    tmp_path: pathlib.Path, scenario_dir="reference", turns=2, reply=None
) -> list[dict]:
    """Record a run with fake engines. On a worker thread, because Playwright's sync
    API keeps an event loop running on the test thread and `engine.run` calls
    `asyncio.run`, which refuses to start inside a running loop."""
    scenario = Scenario.load(ROOT / "scenarios" / scenario_dir)
    out = tmp_path / f"{scenario.name}.jsonl"
    engines = {a: FakeEngine(reply) for a in scenario.actors}
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        pool.submit(
            engine.run, scenario, seed=1, out=out, engines=engines, turns=turns
        ).result()
    return engine.read_records(out)


def write_run(runs_dir: pathlib.Path, name: str, records: list[dict]) -> pathlib.Path:
    path = runs_dir / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(runs_dir: pathlib.Path, **app_kwargs):
    """Start the real app on a free loopback port. Returns (url, stop)."""
    import uvicorn

    from casus.server.app import create_app

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(scenarios_dir=ROOT / "scenarios", runs_dir=runs_dir, **app_kwargs),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    def stop():
        server.should_exit = True
        thread.join(timeout=5)

    return f"http://127.0.0.1:{port}/", stop


def beat(page) -> str:
    return page.locator(".beat.on").inner_text().strip().lower()


def step_to(page, turn: int, beat_name: str) -> None:
    for _ in range(200):
        day = page.locator("#vday").inner_text()
        if day.split()[1].startswith(f"{turn:02d}") and beat(page) == beat_name:
            return
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(30)
    raise AssertionError(f"never reached day {turn}, {beat_name}")
