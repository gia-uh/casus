"""The local app. It binds loopback only and serves one person at a laptop."""

from __future__ import annotations

import functools
import pathlib
import re

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import bundle, engine, studies
from ..scenario import Scenario, ScenarioError

UI = pathlib.Path(__file__).parent.parent.parent.parent / "ui"
APP_SCRIPTS = (*bundle.SCRIPTS, "shell.js")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def scenario_dirs(root: pathlib.Path) -> list[pathlib.Path]:
    """Shipped scenarios, then those behind the private link when it resolves."""
    shipped = sorted(p.parent for p in root.glob("*/scenario.yaml"))
    private = sorted(p.parent for p in root.glob("private/*/scenario.yaml"))
    return [*shipped, *private]


@functools.lru_cache(maxsize=64)
def _verdict(directory: str, stamp: float) -> tuple[bool, tuple[str, ...]]:
    """Full validation is slow (a dry turn, two processes), so it is cached per
    directory and modification time."""
    try:
        Scenario.load(directory)
        return True, ()
    except ScenarioError as exc:
        return False, tuple(str(exc).splitlines())


def _card(directory: pathlib.Path) -> dict:
    stamp = max(p.stat().st_mtime for p in directory.iterdir() if p.is_file())
    valid, findings = _verdict(str(directory), stamp)
    data = Scenario.load(directory, validate=False).data
    return {
        "name": data["name"],
        "dir": directory.name,
        "actors": len(data["actors"]),
        "places": len(data["places"]),
        "turns": data.get("turns"),
        "description": data.get("description", ""),
        "valid": valid,
        "findings": list(findings),
    }


def create_app(
    *, scenarios_dir: pathlib.Path, runs_dir: pathlib.Path, settings=None
) -> FastAPI:
    app = FastAPI(title="casus", docs_url=None, redoc_url=None)
    app.mount("/ui", StaticFiles(directory=UI), name="ui")

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        html = (UI / "app.html").read_text()
        tags = "\n".join(f'<script src="/ui/js/{n}"></script>' for n in APP_SCRIPTS)
        return html.replace("__CASUS_SCRIPTS__", tags).replace(
            "__CASUS_WORLDMAP__", bundle._escape_json((UI / "worldmap.json").read_text())
        )

    @app.get("/api/scenarios")
    def scenarios() -> list[dict]:
        return [_card(d) for d in scenario_dirs(scenarios_dir)]

    @app.get("/api/runs")
    def runs() -> list[dict]:
        return [r.to_json() for r in studies.list_runs(runs_dir)]

    @app.get("/api/runs/{run_id}")
    def run(run_id: str) -> list[dict]:
        path = runs_dir / f"{run_id}.jsonl"
        if (
            not RUN_ID.match(run_id)
            or path.resolve().parent != runs_dir.resolve()
            or not path.is_file()
        ):
            raise HTTPException(404, "no such run")
        return bundle.viewer_records(engine.read_records(path))

    return app
