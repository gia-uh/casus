"""What is on disk under runs/: which transcripts exist and how far each got.

A run's id is its file stem. Reading a run's header costs one line; counting
its turns costs a pass over the file, which is fine for a class's worth of runs.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Literal

Status = Literal["complete", "failed", "incomplete"]


@dataclasses.dataclass(frozen=True)
class RunInfo:
    id: str
    path: pathlib.Path
    scenario: str
    seed: int
    turns_planned: int
    turns_done: int
    status: Status

    def to_json(self) -> dict:
        return {**dataclasses.asdict(self), "path": str(self.path)}


def _scan(path: pathlib.Path) -> RunInfo | None:
    header, states, failed, ended = None, 0, False, False
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    return None
                kind = record.get("kind")
                if header is None:
                    if kind != "scenario":
                        return None
                    header = record
                elif kind == "state":
                    states += 1
                elif kind == "error":
                    failed = True
                elif kind == "end":
                    ended = True
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if header is None:
        return None
    status: Status = "failed" if failed else "complete" if ended else "incomplete"
    return RunInfo(
        id=path.stem,
        path=path,
        scenario=str(header.get("name", "")),
        seed=int(header.get("seed", 0)),
        turns_planned=int(header.get("turns", 0)),
        turns_done=max(states - 1, 0),
        status=status,
    )


def list_runs(runs_dir: pathlib.Path) -> list[RunInfo]:
    """Every readable transcript directly under `runs_dir`, sorted by id."""
    if not runs_dir.is_dir():
        return []
    found = (_scan(p) for p in sorted(runs_dir.glob("*.jsonl")))
    return [info for info in found if info is not None]
