# Slice 5 — settings

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** casus owns its configuration. Values live in `~/.config/casus/config.toml`, the environment wins over the file and every field says where its value came from, secrets are write-only on screen, **Test connection** makes one real call, and a test proves that no credential reaches a transcript, a bundle or a settings response.

**Architecture:** `src/casus/settings.py` holds the `Settings` dataclass from the master plan. `Settings.load` resolves each field from the environment, then the file, then a default, and records the origin; `save` writes a flat TOML file by hand (no new dependency) with mode 0600; `apply_to_env` exports the endpoint and key through the variables lingo reads (`BASE_URL`, `API_KEY`); `probe` makes one short completion through a lingo-built client. `casus run` and `casus serve` load and apply the settings before anything builds an engine. The app gains `GET/PUT /api/settings` and `POST /api/settings/probe`, and the shell gains a settings modal behind a button in `#topactions`.

**Tech Stack:** Python 3.13 (`tomllib` from the standard library), FastAPI, lingo-ai (its `LLM` builds the OpenAI-compatible client), httpx `MockTransport` for every test that would touch a provider, plain JS, pytest, Playwright.

**Specs:** `docs/specs/2026-09-28-interface-design.md` ("Settings"), and the v2 design's "Configuration and secrets" section (`/home/apiad/Workspace/vault/Atlas/Architecture/2026-09-28-casus-general-conflict-simulator-design.md`). Master plan: `docs/plans/2026-09-29-casus-app-plan.md` (the `Settings` interface, `probe`, and the `/settings` rows of the HTTP table are binding).

**Reference for the look:** the settings modal of the reviewed mockup, `openSettings()` in `/home/apiad/Workspace/vault/Efforts/Areas/University/casus-clase/mockups/casus-v2.html`. Slice 1 copied the mockup's whole `<style>` block into `ui/css/app.css`, so `.modal`, `.set`, `.probe`, `.inp`, `.hint`, `.badge` and `.iconbtn` already exist; this slice adds five rules.

## Global Constraints

Everything in the master plan's Global Constraints, plus:

- A secret is write-only. The server never sends a secret's value to the browser, and the browser never displays one: a secret field is an empty password input with a *configured* / *not set* badge.
- A value that came from the environment is never written to the config file. Saving writes only the fields someone changed through the screen.
- The server binds `127.0.0.1` only, and `casus serve` offers no option to change that. This slice adds a test that pins it.
- No test touches the network or the developer's real config. An autouse fixture points `XDG_CONFIG_HOME` at a temporary directory and unsets every variable `settings.py` reads; every provider call in a test goes to an in-memory `httpx.MockTransport`.

### The environment variables

Decided here and documented in the README in Task 8. For each field, the first variable that is set and non-empty wins; then the file; then the default.

| field | variables, highest precedence first | default |
|---|---|---|
| `endpoint` | `CASUS_ENDPOINT`, `BASE_URL` | `https://openrouter.ai/api/v1` |
| `api_key` | `CASUS_API_KEY`, `CASUS_API_KEY_FILE` (path to a file holding the key), `API_KEY` | not set |
| `firecrawl_token` | `FIRECRAWL_API_KEY` | not set |
| `player_model` | `CASUS_PLAYER_MODEL` | `qwen/qwen3-32b` |
| `agent_model` | `CASUS_AGENT_MODEL` | `qwen/qwen3-32b` |
| `run_concurrency` | `CASUS_RUN_CONCURRENCY` | `4` |
| `source_dirs` | `CASUS_SOURCE_DIRS` (split on `os.pathsep`) | none |

`CASUS_*` names are this app's. `BASE_URL` and `API_KEY` are lingo's, and `FIRECRAWL_API_KEY` is Firecrawl's, so a shell set up for either keeps working. `CASUS_API_KEY_FILE` is the name the class README in the vault already uses (`vault/Efforts/Areas/University/casus-clase/README.md`); nothing in the code read it until this slice.

One behaviour changes: with no `BASE_URL` set, a run used to go to the OpenAI client's default host. It now goes to the default endpoint, OpenRouter, which is what every scenario's `qwen/qwen3-32b` model name assumes.

### Not in this slice

- `player_model` is the model the probe calls and the default a later Run dialog offers. It does not yet stand in for an actor whose scenario names no `model`: the validator requires a `model` on every actor (`src/casus/scenario.py`, the `("briefing", "model")` check), and relaxing that is an engine change with its own test.
- Remote access, accounts, a second user. The master plan rules them out.

## Review Focus

Pinned here because this slice owns the code:

- A credential never reaches a transcript or a bundle, including when the provider rejects the key and quotes it back — `tests/test_settings.py::test_a_run_and_its_bundle_carry_no_key`, `::test_a_run_whose_key_is_rejected_leaves_no_trace`, `::test_a_live_run_whose_key_is_rejected_leaves_no_trace`.
- A key saved from the screen and applied to the process environment still reads as "from config.toml" on the next load; otherwise the next key typed into the screen loses to the one applied before it — `tests/test_settings.py::test_a_key_applied_from_the_file_still_reads_as_from_the_file`.
- A PUT with an empty secret keeps the stored secret — `tests/test_server.py::test_a_put_with_an_empty_secret_keeps_the_stored_one`.
- Keys typed in the modal do not reach the viewer or the shell (`Esc` closes the modal, it does not leave the run) — `tests/browser/test_app.py::test_keys_typed_in_the_settings_stay_in_the_settings`.

---

### Task 1: Settings from the file and the environment

**Files:**
- Create: `src/casus/settings.py`
- Modify: `tests/conftest.py` (an autouse isolation fixture), `tests/test_purity.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings` (fields exactly as the master plan), `Settings.load(path=None, env=None)`, `Settings.save(path=None)`, `Settings.public()`, `merge(current, changes, clear=()) -> Settings`, `config_path(env=None) -> Path`, `data_dir(env=None) -> Path`, `SettingsError`, and the constants `FIELDS`, `SECRETS`, `ENV`, `DEFAULTS`.
- `public()` returns `{field: {"value": ..., "origin": "env:NAME" | "config" | "default", "secret": bool}}`; a secret's `value` is `"configured"` or `"not set"`.

- [ ] **Step 1: Isolate every test from the real settings**

Append to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _no_real_settings(tmp_path):
    """No test reads the developer's config file or keys, and no test leaks a
    settings variable into the next one."""
    import os

    from casus import settings

    names = {v for vs in settings.ENV.values() for v in vs} | {"XDG_CONFIG_HOME"}
    saved = {n: os.environ.pop(n, None) for n in names}
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    yield
    for name in names:
        os.environ.pop(name, None)
        if saved[name] is not None:
            os.environ[name] = saved[name]
```

The names come from `settings.ENV`, so a variable added there is isolated without a second edit.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_settings.py`:

```python
"""Settings: where each value comes from, the file, the probe, and the rule that
a credential never reaches a transcript, a bundle or a screen."""

import json
import os
import pathlib
import stat
import tomllib

import pytest

from casus import settings
from casus.settings import Settings, SettingsError, config_path, data_dir, merge

ROOT = pathlib.Path(__file__).parent.parent
SMOKE = ROOT / "scenarios" / "smoke"

#: Recognisable in any file it leaks into, and long enough to be redacted.
FAKE_KEY = "sk-or-v1-casus-leak-5f3a9c1e7b2d40864e1d"


def _write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _mode(path: pathlib.Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _assert_clean(text: str, where: str) -> None:
    assert FAKE_KEY not in text, f"the key is in {where}"
    assert FAKE_KEY[:12] not in text, f"the first 12 characters of the key are in {where}"


# --- where values come from ----------------------------------------------------


def test_with_no_file_and_no_environment_every_field_is_a_default(tmp_path):
    current = Settings.load(path=tmp_path / "none.toml", env={})
    assert current.endpoint == settings.DEFAULTS["endpoint"]
    assert current.api_key is None and current.source_dirs == ()
    assert set(current.origins.values()) == {"default"}


def test_the_file_lives_under_xdg_config_home(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert config_path(env) == tmp_path / "casus" / "config.toml"
    _write(config_path(env), 'player_model = "local/model"\n')
    current = Settings.load(env=env)
    assert (current.player_model, current.origins["player_model"]) == ("local/model", "config")


def test_user_data_lives_under_xdg_data_home(tmp_path):
    """The one home for chats and other per-user data; design and evaluate
    mode both put their sessions under it."""
    assert data_dir({"XDG_DATA_HOME": str(tmp_path)}) == tmp_path / "casus"
    assert data_dir({}).parts[-3:] == (".local", "share", "casus")


def test_the_environment_wins_over_the_file_and_names_its_variable(tmp_path):
    path = _write(tmp_path / "c.toml", 'endpoint = "https://file.test/v1"\n')
    current = Settings.load(path=path, env={"BASE_URL": "http://lingo.test/v1"})
    assert current.endpoint == "http://lingo.test/v1"
    assert current.origins["endpoint"] == "env:BASE_URL"
    both = {"BASE_URL": "http://lingo.test/v1", "CASUS_ENDPOINT": "http://casus.test/v1"}
    assert Settings.load(path=path, env=both).origins["endpoint"] == "env:CASUS_ENDPOINT"


def test_the_key_can_come_from_a_file_named_in_the_environment(tmp_path):
    key_file = _write(tmp_path / "openrouter.token", FAKE_KEY + "\n")
    env = {"CASUS_API_KEY_FILE": str(key_file), "API_KEY": "sk-lower-precedence-000"}
    current = Settings.load(path=tmp_path / "none.toml", env=env)
    assert current.api_key == FAKE_KEY
    assert current.origins["api_key"] == "env:CASUS_API_KEY_FILE"


def test_an_unreadable_key_file_is_an_error_naming_the_variable(tmp_path):
    env = {"CASUS_API_KEY_FILE": str(tmp_path / "missing.token")}
    with pytest.raises(SettingsError, match="CASUS_API_KEY_FILE"):
        Settings.load(path=tmp_path / "none.toml", env=env)


def test_an_empty_variable_counts_as_unset(tmp_path):
    path = _write(tmp_path / "c.toml", 'agent_model = "file/model"\n')
    current = Settings.load(path=path, env={"CASUS_AGENT_MODEL": ""})
    assert current.origins["agent_model"] == "config"


def test_source_dirs_from_the_environment_split_on_the_path_separator(tmp_path):
    env = {"CASUS_SOURCE_DIRS": os.pathsep.join(["/a", "/b c"])}
    current = Settings.load(path=tmp_path / "none.toml", env=env)
    assert current.source_dirs == (pathlib.Path("/a"), pathlib.Path("/b c"))


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ('endpoint = "ftp://x"\n', "endpoint"),
        ("run_concurrency = 0\n", "run_concurrency"),
        ('run_concurrency = "many"\n', "run_concurrency"),
        ('player_model = ""\n', "player_model"),
    ],
)
def test_a_bad_value_is_an_error_naming_the_field_and_where_it_came_from(tmp_path, text, field):
    path = _write(tmp_path / "c.toml", text)
    with pytest.raises(SettingsError, match=rf"{field} \(from config\)"):
        Settings.load(path=path, env={})


def test_a_file_that_is_not_toml_is_an_error_naming_the_file(tmp_path):
    path = _write(tmp_path / "c.toml", "endpoint = \n")
    with pytest.raises(SettingsError, match="c.toml"):
        Settings.load(path=path, env={})


# --- the file --------------------------------------------------------------------


def test_save_writes_a_file_only_this_user_can_read(tmp_path):
    path = tmp_path / "casus" / "config.toml"
    merge(Settings.load(path=path, env={}), {"api_key": FAKE_KEY}).save(path)
    assert _mode(path) == 0o600
    assert tomllib.loads(path.read_text())["api_key"] == FAKE_KEY


def test_save_tightens_a_file_that_others_could_read(tmp_path):
    path = _write(tmp_path / "config.toml", 'agent_model = "a/b"\n')
    path.chmod(0o644)
    merge(Settings.load(path=path, env={}), {"api_key": FAKE_KEY}).save(path)
    assert _mode(path) == 0o600
    assert Settings.load(path=path, env={}).agent_model == "a/b"


NASTY = [
    'quote " and backslash \\',
    "new\nline, tab\t, return\r, formfeed\f, backspace\b",
    'x"\napi_key = "stolen',
    "nul \x00 and del \x7f",
    "unicode: é, 🙂,  , ﻿",
    "".join(chr(i) for i in range(0x80)),
]


@pytest.mark.parametrize("value", NASTY, ids=range(len(NASTY)))
def test_any_string_survives_the_file(tmp_path, value):
    path = tmp_path / "config.toml"
    changes = {"api_key": value, "player_model": value, "source_dirs": [value]}
    merge(Settings.load(path=path, env={}), changes).save(path)
    data = tomllib.loads(path.read_text())
    assert (data["api_key"], data["player_model"]) == (value, value)
    assert data["source_dirs"] == [value]
    assert set(data) == {"api_key", "player_model", "source_dirs"}


def test_a_value_from_the_environment_is_never_written_to_the_file(tmp_path):
    path = _write(tmp_path / "config.toml", 'api_key = "sk-stored-in-the-file-0001"\n')
    env = {"CASUS_API_KEY": FAKE_KEY}
    merge(Settings.load(path=path, env=env), {"agent_model": "x/y"}).save(path)
    text = path.read_text()
    assert FAKE_KEY not in text
    assert tomllib.loads(text)["api_key"] == "sk-stored-in-the-file-0001"


def test_an_empty_secret_keeps_the_stored_one(tmp_path):
    path = tmp_path / "config.toml"
    merge(Settings.load(path=path, env={}), {"api_key": FAKE_KEY}).save(path)
    merge(Settings.load(path=path, env={}), {"api_key": "", "agent_model": "x/y"}).save(path)
    assert Settings.load(path=path, env={}).api_key == FAKE_KEY


def test_clearing_a_secret_removes_it_from_the_file(tmp_path):
    path = tmp_path / "config.toml"
    merge(Settings.load(path=path, env={}), {"api_key": FAKE_KEY}).save(path)
    merge(Settings.load(path=path, env={}), {}, clear=["api_key"]).save(path)
    assert FAKE_KEY not in path.read_text()
    assert Settings.load(path=path, env={}).origins["api_key"] == "default"


def test_only_known_fields_can_change_and_only_secrets_can_be_cleared(tmp_path):
    current = Settings.load(path=tmp_path / "none.toml", env={})
    with pytest.raises(SettingsError, match="unknown setting"):
        merge(current, {"api_url": "x"})
    with pytest.raises(SettingsError, match="only a secret"):
        merge(current, {}, clear=["endpoint"])


# --- what leaves this module ------------------------------------------------------


def test_public_says_configured_and_never_shows_a_secret(tmp_path):
    env = {"CASUS_API_KEY": FAKE_KEY}
    shown = Settings.load(path=tmp_path / "none.toml", env=env).public()
    assert shown["api_key"] == {
        "value": "configured",
        "origin": "env:CASUS_API_KEY",
        "secret": True,
    }
    assert shown["firecrawl_token"]["value"] == "not set"
    assert shown["endpoint"]["secret"] is False
    _assert_clean(json.dumps(shown), "public()")
```

Append to `tests/test_purity.py`:

```python
@pytest.mark.parametrize("module", [state, proxy, ruleset, resolver], ids=lambda m: m.__name__)
def test_the_core_never_sees_the_settings(module):
    """Credentials reach lingo through the environment the command line sets up.
    The engine core does not import them and does not name them."""
    assert "settings" not in pathlib.Path(module.__file__).read_text()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_settings.py tests/test_purity.py -q`
Expected: FAIL. `tests/conftest.py` cannot import `casus.settings` (`ImportError: cannot import name 'settings' from 'casus'`), so every test errors at setup.

- [ ] **Step 4: Implement**

Create `src/casus/settings.py`:

```python
"""What this installation is configured with, and where each value came from.

Values live in `~/.config/casus/config.toml` (under `$XDG_CONFIG_HOME` when it
is set), outside the project. The environment wins over the file, and every
field records whether its value came from a variable, the file or the default,
so a value overridden from outside is never a mystery on the settings screen.

`public()` never returns a secret's value: it says "configured" or "not set".
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import tomllib
from collections.abc import Iterable, Mapping

FIELDS = (
    "endpoint",
    "api_key",
    "firecrawl_token",
    "player_model",
    "agent_model",
    "run_concurrency",
    "source_dirs",
)
SECRETS = frozenset({"api_key", "firecrawl_token"})

#: Variables per field, highest precedence first. `CASUS_*` are this app's own;
#: `BASE_URL` and `API_KEY` are lingo's and `FIRECRAWL_API_KEY` is Firecrawl's,
#: so a shell already set up for either keeps working. A `_FILE` variable names
#: a file holding the value, which keeps the key itself out of shell history.
ENV = {
    "endpoint": ("CASUS_ENDPOINT", "BASE_URL"),
    "api_key": ("CASUS_API_KEY", "CASUS_API_KEY_FILE", "API_KEY"),
    "firecrawl_token": ("FIRECRAWL_API_KEY",),
    "player_model": ("CASUS_PLAYER_MODEL",),
    "agent_model": ("CASUS_AGENT_MODEL",),
    "run_concurrency": ("CASUS_RUN_CONCURRENCY",),
    "source_dirs": ("CASUS_SOURCE_DIRS",),
}

DEFAULTS: dict[str, object] = {
    "endpoint": "https://openrouter.ai/api/v1",
    "api_key": None,
    "firecrawl_token": None,
    "player_model": "qwen/qwen3-32b",
    "agent_model": "qwen/qwen3-32b",
    "run_concurrency": 4,
    "source_dirs": (),
}


class SettingsError(ValueError):
    """A value that cannot be used, named with the place it came from."""


def config_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or str(pathlib.Path.home() / ".config")
    return pathlib.Path(base) / "casus" / "config.toml"


def data_dir(env: Mapping[str, str] | None = None) -> pathlib.Path:
    """Per-user data that is not configuration: the agents' chat sessions."""
    env = os.environ if env is None else env
    base = env.get("XDG_DATA_HOME") or str(pathlib.Path.home() / ".local" / "share")
    return pathlib.Path(base) / "casus"


@dataclasses.dataclass
class Settings:
    endpoint: str
    api_key: str | None
    firecrawl_token: str | None
    player_model: str
    agent_model: str
    run_concurrency: int
    source_dirs: tuple[pathlib.Path, ...]
    origins: dict[str, str]  # field -> "env:NAME" | "config" | "default"

    @classmethod
    def load(
        cls, path: pathlib.Path | None = None, env: Mapping[str, str] | None = None
    ) -> Settings:
        env = os.environ if env is None else env
        path = path or config_path(env)
        stored = _read(path)
        values: dict[str, object] = {}
        origins: dict[str, str] = {}
        for name in FIELDS:
            raw, origin = _pick(name, env, stored)
            values[name] = _coerce(name, raw, origin)
            origins[name] = origin
        return cls(**values, origins=origins)

    def save(self, path: pathlib.Path | None = None) -> None:
        """Write the fields whose origin is the file, keeping the others the file
        already holds. A value that came from the environment or the defaults is
        never copied into it, so a key exported in a shell stays in the shell."""
        path = path or config_path()
        stored = {k: v for k, v in _read(path).items() if k in FIELDS}
        for name in FIELDS:
            if self.origins.get(name) != "config":
                continue
            value = getattr(self, name)
            if value is None:
                stored.pop(name, None)
            elif name == "source_dirs":
                stored[name] = [str(p) for p in value]
            else:
                stored[name] = value
        _write_private(path, _dump(stored))

    def public(self) -> dict:
        """Every field as the screen may show it: a secret is "configured" or
        "not set", never its value."""
        out = {}
        for name in FIELDS:
            value = getattr(self, name)
            if name in SECRETS:
                shown: object = "configured" if value else "not set"
            elif name == "source_dirs":
                shown = [str(p) for p in value]
            else:
                shown = value
            out[name] = {
                "value": shown,
                "origin": self.origins[name],
                "secret": name in SECRETS,
            }
        return out


def merge(
    current: Settings, changes: Mapping[str, object], clear: Iterable[str] = ()
) -> Settings:
    """`current` with `changes` as values for the file. An empty secret leaves
    the stored one alone: the screen never receives a secret, so it always sends
    that field empty unless someone typed a new one. Removing a secret takes
    naming it in `clear`."""
    values = {name: getattr(current, name) for name in FIELDS}
    origins = dict(current.origins)
    for name, raw in changes.items():
        if name not in FIELDS:
            raise SettingsError(f"unknown setting {name!r}")
        if name in SECRETS and not raw:
            continue
        values[name] = _coerce(name, raw, "the settings screen")
        origins[name] = "config"
    for name in clear:
        if name not in SECRETS:
            raise SettingsError(f"only a secret can be cleared, not {name!r}")
        values[name] = None
        origins[name] = "config"
    return Settings(**values, origins=origins)


# --- reading ------------------------------------------------------------------


def _read(path: pathlib.Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise SettingsError(f"{path}: {exc.strerror}") from None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{path}: {exc}") from None


def _pick(name: str, env: Mapping[str, str], stored: Mapping) -> tuple[object, str]:
    for var in ENV[name]:
        value = env.get(var)
        if not value:  # an empty variable is an unset one
            continue
        if var.endswith("_FILE"):
            try:
                value = pathlib.Path(value).expanduser().read_text(encoding="utf-8")
            except OSError as exc:
                raise SettingsError(f"{var}: cannot read {value}: {exc.strerror}") from None
        return value, f"env:{var}"
    if name in stored:
        return stored[name], "config"
    return DEFAULTS[name], "default"


def _coerce(name: str, raw: object, origin: str) -> object:
    """The typed value of a field. An error names the field and its origin and
    never quotes a secret's value."""
    try:
        if name in SECRETS:
            return (str(raw).strip() or None) if raw is not None else None
        if name == "run_concurrency":
            if isinstance(raw, bool):
                raise ValueError("must be a whole number")
            number = int(str(raw).strip())
            if number < 1:
                raise ValueError("must be at least 1")
            return number
        if name == "source_dirs":
            items = str(raw).split(os.pathsep) if isinstance(raw, str) else list(raw)
            return tuple(pathlib.Path(str(p)).expanduser() for p in items if str(p).strip())
        text = str(raw).strip()
        if not text:
            raise ValueError("must not be empty")
        if name == "endpoint" and not text.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return text
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{name} (from {origin}): {exc}") from None


# --- writing ------------------------------------------------------------------

_ESCAPES = {
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
    '"': '\\"',
    "\\": "\\\\",
}


def _string(text: str) -> str:
    """A TOML basic string. Control characters are escaped, so a value cannot
    end its line and start a key of its own."""
    out = []
    for ch in text:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    return _string(str(value))


def _dump(stored: Mapping[str, object]) -> str:
    lines = ["# casus settings. Environment variables win over this file."]
    lines += [f"{name} = {_value(stored[name])}" for name in FIELDS if name in stored]
    return "\n".join(lines) + "\n"


def _write_private(path: pathlib.Path, text: str) -> None:
    """Replace `path` with `text`, readable by this user only. The new content
    goes to a 0600 file beside it that then takes its name, so a crash leaves
    the old file whole and a file someone made readable by others is replaced
    by one that is not."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
```

The file holds only the fields in `FIELDS`; anything else a person typed into it is dropped on the next save. That keeps `_dump` total over what it writes: strings, integers and lists of strings.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_settings.py tests/test_purity.py -q`
Expected: PASS (25 tests in `test_settings.py`, 8 in `test_purity.py`).

- [ ] **Step 6: Break the escaping on purpose**

In `_string`, delete the `elif ord(ch) < 0x20 ...` branch and its `out.append`. Run `uv run pytest tests/test_settings.py -q -k survives`. Expected: FAIL on the cases holding `\x00` and the full ASCII range (`tomllib` rejects a raw control character). Restore the branch.

- [ ] **Step 7: Commit**

```bash
git add src/casus/settings.py tests/test_settings.py tests/conftest.py tests/test_purity.py
git commit -m "feat(settings): read the config file and the environment, with origins"
```

---

### Task 2: Handing the settings to lingo, and redaction

**Files:**
- Modify: `src/casus/settings.py`, `tests/conftest.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `Settings`, `merge` (Task 1); lingo's `LLM`, which reads `BASE_URL` and `API_KEY` from `os.environ` in its constructor when `base_url` / `api_key` are not passed (`lingo/llm.py`, `LLM.__init__`).
- Produces: `Settings.apply_to_env()`, `redact(text, secrets=None) -> str`, and the constants `EXPORTED`, `SECRET_PREFIX`, `REDACTED`.

`apply_to_env` exports `endpoint` as `BASE_URL`, `api_key` as `API_KEY` and `firecrawl_token` as `FIRECRAWL_API_KEY`. It records what it set, and `load` ignores a variable whose value is one it set itself. Without that, a key saved from the screen and applied would read as `env:API_KEY` on the next load, and the next key typed into the screen would lose to it: exactly the "something else was overriding it" hour the v2 design says nobody should lose.

- [ ] **Step 1: Write the failing tests**

In `tests/test_settings.py`, add to the imports:

```python
from lingo import LLM

from casus.settings import redact
```

and append:

```python
def _configured(key: str = FAKE_KEY, endpoint: str = "http://provider.test/v1") -> Settings:
    """Save a key and an endpoint the way the settings screen does, then load
    and apply them the way `casus serve` does."""
    merge(Settings.load(), {"api_key": key, "endpoint": endpoint}).save()
    current = Settings.load()
    current.apply_to_env()
    return current


def test_apply_to_env_hands_lingo_the_endpoint_and_the_key():
    _configured()
    llm = LLM(model="m")
    assert llm.client.api_key == FAKE_KEY
    assert str(llm.client.base_url).startswith("http://provider.test/v1")


def test_a_key_applied_from_the_file_still_reads_as_from_the_file():
    """Otherwise the next load reports it as coming from API_KEY, and the key
    typed into the screen after that loses to the one applied before it."""
    _configured()
    assert Settings.load().origins["api_key"] == "config"
    _configured(key="sk-or-v1-the-second-key-0000000")
    assert Settings.load().api_key == "sk-or-v1-the-second-key-0000000"
    assert os.environ["API_KEY"] == "sk-or-v1-the-second-key-0000000"


def test_a_key_the_user_exported_stays_theirs():
    os.environ["API_KEY"] = "sk-exported-by-the-user-00000"
    current = Settings.load()
    current.apply_to_env()
    assert Settings.load().origins["api_key"] == "env:API_KEY"
    merge(Settings.load(), {}, clear=["api_key"]).save()
    Settings.load().apply_to_env()
    assert os.environ["API_KEY"] == "sk-exported-by-the-user-00000"


def test_clearing_the_key_takes_it_back_out_of_the_environment():
    _configured()
    merge(Settings.load(), {}, clear=["api_key"]).save()
    Settings.load().apply_to_env()
    assert "API_KEY" not in os.environ


def test_redact_removes_a_secret_and_its_start():
    text = f"key {FAKE_KEY}, quoted as {FAKE_KEY[:14]}…"
    expected = f"key [redacted], quoted as [redacted]{FAKE_KEY[12:14]}…"
    assert redact(text, [FAKE_KEY]) == expected


def test_redact_leaves_short_placeholders_alone():
    assert redact("ollama refused", ["ollama"]) == "ollama refused"


def test_redact_defaults_to_the_exported_secrets():
    _configured()
    assert FAKE_KEY not in redact(f"echo {FAKE_KEY}")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_settings.py -q`
Expected: FAIL with `ImportError: cannot import name 'redact' from 'casus.settings'`.

- [ ] **Step 3: Implement**

In `src/casus/settings.py`, add after `DEFAULTS`:

```python
#: What `apply_to_env` exports: field -> the variable its reader looks at.
EXPORTED = {
    "endpoint": "BASE_URL",
    "api_key": "API_KEY",
    "firecrawl_token": "FIRECRAWL_API_KEY",
}

#: Secrets shorter than this are placeholders ("ollama", "lm-studio") that a
#: local server ignores; redacting them would only mangle text that names the
#: server. A longer secret is redacted whole and by its first 12 characters,
#: because a provider that rejects a key often quotes its start back.
SECRET_PREFIX = 12
REDACTED = "[redacted]"

#: Variables `apply_to_env` set in this process, with the value it set. `load`
#: ignores them: otherwise a key saved from the settings screen would read as
#: "from the environment" on the next load, and then beat the next save.
_APPLIED: dict[str, str] = {}
```

In `Settings.load`, replace `env = os.environ if env is None else env` with:

```python
        env = _user_env() if env is None else env
```

In `Settings.save`, replace `path = path or config_path()` with:

```python
        path = path or config_path(_user_env())
```

Add this method to `Settings`, after `public`:

```python
    def apply_to_env(self) -> None:
        """Export the endpoint and the keys through the variables lingo and
        Firecrawl read. lingo reads them when an `LLM` is built, so a client
        built before this call keeps what it had and the next one gets these."""
        for name, var in EXPORTED.items():
            value = getattr(self, name)
            if value:
                if os.environ.get(var) != value:
                    os.environ[var] = value
                    _APPLIED[var] = value
            elif var in _APPLIED and os.environ.get(var) == _APPLIED.pop(var):
                del os.environ[var]
```

Add after `merge`:

```python
def redact(text: str, secrets: Iterable[str | None] | None = None) -> str:
    """`text` with every secret, and the first 12 characters of each, replaced.
    With no `secrets`, the ones exported to this process's environment."""
    if secrets is None:
        secrets = (os.environ.get(var) for var in ("API_KEY", "FIRECRAWL_API_KEY"))
    found = {s for s in secrets if s and len(s) >= SECRET_PREFIX}
    for secret in sorted(found, key=len, reverse=True):
        text = text.replace(secret, REDACTED).replace(secret[:SECRET_PREFIX], REDACTED)
    return text
```

Add at the top of the `# --- reading` section:

```python
def _user_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if _APPLIED.get(k) != v}
```

Extend the module docstring's last paragraph to:

```python
A secret leaves this module in the clear only through `apply_to_env`, which
hands the provider key to lingo the way lingo reads it. `public()` says
"configured" or "not set", and `redact()` takes secrets out of any text a
person will see.
```

In `tests/conftest.py`, make `_no_real_settings` reset the record of applied variables, since it is module state. Replace the fixture body with:

```python
    import os

    from casus import settings

    names = {v for vs in settings.ENV.values() for v in vs} | {"XDG_CONFIG_HOME"}
    saved = {n: os.environ.pop(n, None) for n in names}
    applied = dict(settings._APPLIED)
    settings._APPLIED.clear()
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    yield
    for name in names:
        os.environ.pop(name, None)
        if saved[name] is not None:
            os.environ[name] = saved[name]
    settings._APPLIED.clear()
    settings._APPLIED.update(applied)
```

(`EXPORTED`'s three variables are all in `ENV` already, so the fixture restores them too.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_settings.py -q`
Expected: PASS (32 tests).

- [ ] **Step 5: Break it on purpose**

In `Settings.load`, put back `env = os.environ if env is None else env`. Run `uv run pytest tests/test_settings.py -q -k "still_reads_as_from_the_file"`. Expected: FAIL (`'env:API_KEY' == 'config'`). Restore `_user_env()`.

- [ ] **Step 6: Commit**

```bash
git add src/casus/settings.py tests/test_settings.py tests/conftest.py
git commit -m "feat(settings): hand the endpoint and key to lingo, and redact secrets from text"
```

---

### Task 3: The connection probe

**Files:**
- Modify: `src/casus/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `lingo.LLM(model, api_key, base_url)` and its `.client`, an `openai.AsyncOpenAI`; `redact` (Task 2).
- Produces: `async def probe(settings: Settings) -> dict` returning `{"ok": bool, "model": str | None, "latency_ms": int | None, "error": str | None}`, and the constants `PROBE_PROMPT`, `PROBE_MAX_TOKENS`, `PROBE_TIMEOUT`.

The probe builds the client with lingo's `LLM`, so the base URL and key reach the wire the way a run's do. It does not call `LLM.chat`: `chat` streams, and lingo drops the `model` field of the chunks, while the non-streamed response names the model that actually answered (a router may substitute another). It makes one try (`max_retries=0`) under a wall-clock limit, because httpx timeouts are per operation and a hung endpoint must come back as a result, not a spinner.

The tests replace the network with `httpx.MockTransport` by wrapping `openai.AsyncOpenAI`, which is what lingo's `LLM` constructs. That exercises the real path: `Settings` → lingo → the OpenAI client → an HTTP request whose URL and `Authorization` header the test can read.

- [ ] **Step 1: Write the failing tests**

In `tests/test_settings.py`, add to the imports:

```python
import asyncio

import httpx
import openai

from casus.settings import probe
```

and append:

```python
DECLARATION = {"actions": [{"type": "hold"}], "rationale": "wait", "assessment": "they wait"}


def _provider(monkeypatch, handler) -> list[dict]:
    """Route every OpenAI client lingo builds to `handler`, in memory. Returns
    the requests that reached it, so a test can check what went on the wire."""
    calls: list[dict] = []
    real = openai.AsyncOpenAI

    def seen(request: httpx.Request):
        calls.append(
            {
                "url": str(request.url),
                "authorization": request.headers.get("authorization"),
                "body": json.loads(request.content or b"{}"),
            }
        )
        return handler(request)

    def make(**kwargs):
        transport = httpx.MockTransport(seen)
        return real(**kwargs, http_client=httpx.AsyncClient(transport=transport))

    monkeypatch.setattr(openai, "AsyncOpenAI", make)
    return calls


def _completion(content: str, model: str = "fake/answered") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "fake",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def _answering(request: httpx.Request) -> httpx.Response:
    """A provider that answers a probe with a word and a player with a hold."""
    body = json.loads(request.content)
    if "response_format" in body:
        return _completion(json.dumps(DECLARATION))
    return _completion("ready")


def _rejecting(request: httpx.Request) -> httpx.Response:
    """A provider that refuses the key and quotes it back, as some do."""
    key = request.headers["authorization"].removeprefix("Bearer ")
    return httpx.Response(
        401, json={"error": {"message": f"Incorrect API key provided: {key}", "code": 401}}
    )


def test_the_probe_reports_the_model_that_answered(monkeypatch):
    calls = _provider(monkeypatch, _answering)
    result = asyncio.run(probe(_configured()))
    assert result["ok"] is True and result["error"] is None
    assert result["model"] == "fake/answered"
    assert isinstance(result["latency_ms"], int) and result["latency_ms"] >= 0
    [call] = calls
    assert call["url"] == "http://provider.test/v1/chat/completions"
    assert call["authorization"] == f"Bearer {FAKE_KEY}"
    assert call["body"]["model"] == settings.DEFAULTS["player_model"]
    assert call["body"]["max_tokens"] == settings.PROBE_MAX_TOKENS


def test_a_rejected_key_is_reported_without_the_key(monkeypatch):
    calls = _provider(monkeypatch, _rejecting)
    result = asyncio.run(probe(_configured()))
    assert result["ok"] is False and "401" in result["error"]
    assert len(calls) == 1, "the probe must not retry"
    _assert_clean(json.dumps(result), "the probe result")


def test_the_probe_without_a_key_makes_no_call(monkeypatch):
    calls = _provider(monkeypatch, _answering)
    result = asyncio.run(probe(Settings.load()))
    assert result == {
        "ok": False,
        "model": None,
        "latency_ms": None,
        "error": "no API key is set",
    }
    assert calls == []


def test_a_hung_endpoint_is_a_result_not_a_hang(monkeypatch):
    async def hang(request):
        await asyncio.sleep(5)
        return _completion("late")

    _provider(monkeypatch, hang)
    monkeypatch.setattr(settings, "PROBE_TIMEOUT", 0.2)
    result = asyncio.run(probe(_configured()))
    assert result["ok"] is False and "no answer within 0.2 s" in result["error"]


def test_an_unreachable_endpoint_is_a_result(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    _provider(monkeypatch, refuse)
    result = asyncio.run(probe(_configured()))
    assert result["ok"] is False and "Connection" in result["error"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_settings.py -q`
Expected: FAIL with `ImportError: cannot import name 'probe' from 'casus.settings'`.

- [ ] **Step 3: Implement**

In `src/casus/settings.py`, add to the imports:

```python
import asyncio
import time

from lingo import LLM
```

add after `REDACTED`:

```python
PROBE_PROMPT = "Reply with the single word: ready."
PROBE_MAX_TOKENS = 16
PROBE_TIMEOUT = 20.0
```

and after `redact`:

```python
async def probe(settings: Settings) -> dict:
    """One short completion against the configured endpoint with the player
    model. Reports the model that answered and the latency, or the error.

    The client is lingo's, built from these settings, so the endpoint and key
    reach the wire the way a run's do. The call itself is not streamed: a
    non-streamed response names the model that actually answered (a router may
    substitute another), and lingo's `chat` does not keep that name. One try,
    no retries, and a wall-clock limit, because a hung endpoint is a result."""
    if not settings.api_key:
        return {"ok": False, "model": None, "latency_ms": None, "error": "no API key is set"}
    started = time.monotonic()
    try:
        llm = LLM(
            model=settings.player_model, api_key=settings.api_key, base_url=settings.endpoint
        )
        client = llm.client.with_options(max_retries=0)
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.player_model,
                messages=[{"role": "user", "content": PROBE_PROMPT}],
                max_tokens=PROBE_MAX_TOKENS,
            ),
            PROBE_TIMEOUT,
        )
    except TimeoutError:
        error = f"no answer within {PROBE_TIMEOUT:g} s"
    except Exception as exc:  # noqa: BLE001 - every failure is a result to show
        error = f"{type(exc).__name__}: {exc}"
    else:
        return {
            "ok": True,
            "model": response.model or settings.player_model,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "error": None,
        }
    return {
        "ok": False,
        "model": None,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "error": redact(error, (settings.api_key, settings.firecrawl_token))[:500],
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_settings.py -q`
Expected: PASS (37 tests).

- [ ] **Step 5: Break it on purpose**

In `probe`, change the last `"error"` line to `"error": error[:500],`. Run `uv run pytest tests/test_settings.py -q -k rejected_key_is_reported`. Expected: FAIL with `the key is in the probe result`. Restore the `redact(...)` call.

- [ ] **Step 6: Commit**

```bash
git add src/casus/settings.py tests/test_settings.py
git commit -m "feat(settings): probe the endpoint with one short call, errors redacted"
```

---

### Task 4: The leak test

**Files:**
- Test: `tests/test_settings.py`
- Modify (when slice 3 has landed): `src/casus/engine.py` (`_error_text`)

**Interfaces:**
- Consumes: `engine.run`, `engine.engine_for` (through `run`'s default engines), `bundle.bundle`, and, when slice 3 has landed, `engine._error_text(exc)`, `RunManager(runs_dir)`, `RunManager.start(scenario_dir, *, seed, turns, model) -> str` and `RunManager.subscribe(run_id)`.

These tests configure a recognisable fake key the way a person does (saved from the screen, then applied), play a run through real lingo engines against the in-memory provider, and grep what came out. A test that finds nothing proves nothing unless the key was in use, so each one also asserts that requests went out carrying the key.

The one place a key can plausibly reach a record is an error. Slice 3 makes `engine.run_async` write any exception from the turn loop as an `error` record, with the text `_error_text(exc)` gives: `"<TypeName>: <message>"`. When a provider rejects the key and quotes it back, as `_rejecting` does, that message holds the key, and the viewer, the bundle and every copy of the transcript carry it. So once slice 3 has landed, `test_a_run_whose_key_is_rejected_leaves_no_trace` fails until `_error_text` redacts (Step 3). Before slice 3 lands, the engine writes no error record for a provider failure, that test passes, and the live-run test skips because `casus.server.runs` does not exist. Slice 5 depends only on slice 1, so these tests bind whichever of slices 3 and 5 lands second.

- [ ] **Step 1: Write the tests**

In `tests/test_settings.py`, add to the imports:

```python
import contextlib

from casus import bundle, engine
from casus.scenario import Scenario
```

and append:

```python
def test_a_run_and_its_bundle_carry_no_key(tmp_path, monkeypatch):
    """The key is on every request of a real lingo run and in neither file."""
    calls = _provider(monkeypatch, _answering)
    _configured()
    out = tmp_path / "run.jsonl"
    engine.run(Scenario.load(SMOKE), seed=1, out=out, turns=1)
    assert calls, "no request reached the provider, so this test checked nothing"
    assert all(c["authorization"] == f"Bearer {FAKE_KEY}" for c in calls)
    _assert_clean(out.read_text(), "the transcript")
    _assert_clean(bundle.bundle(out, tmp_path / "run.html").read_text(), "the bundle")


def test_a_run_whose_key_is_rejected_leaves_no_trace(tmp_path, monkeypatch):
    calls = _provider(monkeypatch, _rejecting)
    _configured()
    out = tmp_path / "run.jsonl"
    with pytest.raises(openai.AuthenticationError):
        engine.run(Scenario.load(SMOKE), seed=1, out=out, turns=1)
    assert calls
    _assert_clean(out.read_text(), "the transcript")
    _assert_clean(bundle.bundle(out, tmp_path / "run.html").read_text(), "the bundle")


def test_a_live_run_whose_key_is_rejected_leaves_no_trace(tmp_path, monkeypatch):
    """A live run's failure is written for the viewer to show. What it writes
    must not quote the key the provider quoted back."""
    runs = pytest.importorskip("casus.server.runs", reason="slice 3 adds live runs")
    calls = _provider(monkeypatch, _rejecting)
    _configured()
    (tmp_path / "runs").mkdir()
    manager = runs.RunManager(tmp_path / "runs")

    async def play() -> tuple[str, list[dict]]:
        run_id = await manager.start(SMOKE, seed=1, turns=1, model=None)
        seen: list[dict] = []

        async def drain():
            async for record in manager.subscribe(run_id):
                seen.append(record)
                if record["kind"] in ("end", "error"):
                    return

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(drain(), 10)
        return run_id, seen

    run_id, seen = asyncio.run(play())
    assert calls
    _assert_clean(json.dumps(seen), "the live stream")
    _assert_clean((tmp_path / "runs" / f"{run_id}.jsonl").read_text(), "the transcript")
```

The run uses `smoke` with no narrator (the default `narrator_engine=None`), so every request is a player's declaration and `_answering` can answer all of them with the same hold.

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_settings.py -q -k "carry_no_key or leaves_no_trace"`
Expected, with slice 3 on `main` (check with `grep -n "def _error_text" src/casus/engine.py`): `test_a_run_and_its_bundle_carry_no_key` PASSES; `test_a_run_whose_key_is_rejected_leaves_no_trace` and `test_a_live_run_whose_key_is_rejected_leaves_no_trace` FAIL with `the key is in the transcript`, because the `error` record quotes the provider's 401 message. Without slice 3: the first two PASS and the live-run test SKIPS; go to Step 4.

- [ ] **Step 3: Redact the error text the engine records**

In `src/casus/engine.py`, add to the imports:

```python
from .settings import redact
```

and make the last line of slice 3's `_error_text` go through `redact`:

```python
def _error_text(exc: Exception) -> str:
    """A rule's failure reads as the rule reported it. Anything else is named by
    its type too, because `str()` of a timeout or a dropped connection may be
    empty. A provider that rejects a key may quote it back, and this text goes
    into the transcript and every bundle made from it, so secrets are redacted."""
    if isinstance(exc, RuleFailed):
        return str(exc)
    return redact(f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)
```

`redact()` with no second argument uses the secrets exported to the process environment, and lingo read the key from there (`API_KEY`), so the key being redacted is the key that was used. `engine.py` is not part of the engine core, so the purity rule allows the import; `test_the_core_never_sees_the_settings` still passes. Run `uv run pytest tests/test_settings.py tests/test_engine.py -q`. Expected: PASS, slice 3's `test_an_endpoint_that_fails_is_recorded_and_the_run_stops` included (its message holds no secret).

- [ ] **Step 4: Break it on purpose**

In `src/casus/engine.py`, find the line that writes the `end` record (`grep -n '"kind": "end"' src/casus/engine.py`; after slice 3 it is awaited) and add the key's start to that dict: `"note": __import__("os").environ["API_KEY"][:12]`. Run `uv run pytest tests/test_settings.py -q -k carry_no_key`. Expected: FAIL with `the first 12 characters of the key are in the transcript`. Revert that line and run the test again: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_settings.py src/casus/engine.py
git commit -m "test(settings): no key in a transcript, a bundle or a live stream"
```

(Leave `src/casus/engine.py` out of the `git add` if slice 3 has not landed and Step 3 was skipped.)

---

### Task 5: The settings endpoints

**Files:**
- Modify: `src/casus/server/app.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `Settings`, `SettingsError`, `merge`, `probe` (Tasks 1–3).
- Produces: `GET /api/settings` → `Settings.public()`; `PUT /api/settings` with a partial body `{endpoint?, api_key?, firecrawl_token?, player_model?, agent_model?, run_concurrency?, source_dirs?, clear?: ["api_key" | "firecrawl_token"]}` → the saved, reloaded and applied `Settings.public()`, or 422 with the reason; `POST /api/settings/probe` → `probe()`'s dict. `create_app`'s `settings` parameter gets its master-plan type, `Settings | None`.

The app holds the settings it runs with. `casus serve` loads and applies them before building the app (Task 6); with `settings=None` the app loads them on the first request. A PUT merges the body into them, saves to the default path, loads again (so the response shows the environment winning where it does), applies the result to the process environment, and keeps it. A run started after the PUT builds its engines with the new values; a run already playing keeps its clients.

- [ ] **Step 1: Write the failing tests**

In `tests/test_server.py`, add to the imports:

```python
import os
import stat

from casus.settings import Settings, config_path, merge
```

and append:

```python
FAKE_KEY = "sk-or-v1-casus-server-1b9f04e27a6c55d0"


def _saved_key(key: str = FAKE_KEY) -> None:
    merge(Settings.load(), {"api_key": key}).save()


def test_settings_are_served_without_their_secrets(client):
    _saved_key()
    response = client.get("/api/settings")
    assert response.json()["api_key"] == {
        "value": "configured",
        "origin": "config",
        "secret": True,
    }
    assert FAKE_KEY[:12] not in response.text


def test_a_put_saves_the_file_and_applies_it(client):
    body = {"endpoint": "http://127.0.0.1:1234/v1", "api_key": FAKE_KEY}
    response = client.put("/api/settings", json=body)
    assert response.status_code == 200, response.text
    assert FAKE_KEY[:12] not in response.text
    assert response.json()["endpoint"] == {
        "value": "http://127.0.0.1:1234/v1",
        "origin": "config",
        "secret": False,
    }
    assert os.environ["API_KEY"] == FAKE_KEY
    assert os.environ["BASE_URL"] == "http://127.0.0.1:1234/v1"
    assert stat.S_IMODE(config_path().stat().st_mode) == 0o600


def test_a_put_with_an_empty_secret_keeps_the_stored_one(client):
    _saved_key()
    response = client.put("/api/settings", json={"api_key": "", "player_model": "other/model"})
    assert response.json()["api_key"]["value"] == "configured"
    assert Settings.load().api_key == FAKE_KEY


def test_clearing_a_secret_takes_it_out_of_the_file_and_the_environment(client):
    client.put("/api/settings", json={"api_key": FAKE_KEY})
    response = client.put("/api/settings", json={"clear": ["api_key"]})
    assert response.json()["api_key"]["value"] == "not set"
    assert "API_KEY" not in os.environ
    assert FAKE_KEY not in config_path().read_text()


@pytest.mark.parametrize(
    "body",
    [
        {"api_url": "x"},
        {"clear": ["endpoint"]},
        {"endpoint": "ftp://x"},
        {"run_concurrency": 0},
        {"player_model": "   "},
    ],
)
def test_a_bad_update_is_refused_and_changes_nothing(client, body):
    before = client.get("/api/settings").json()
    assert client.put("/api/settings", json=body).status_code == 422
    assert client.get("/api/settings").json() == before
    assert not config_path().exists()


def test_a_field_the_environment_overrides_says_so_after_a_put(client, monkeypatch):
    monkeypatch.setenv("CASUS_PLAYER_MODEL", "env/model")
    body = client.put("/api/settings", json={"player_model": "file/model"}).json()
    assert body["player_model"] == {
        "value": "env/model",
        "origin": "env:CASUS_PLAYER_MODEL",
        "secret": False,
    }


def test_the_probe_endpoint_returns_what_the_probe_found(client, monkeypatch):
    found = {"ok": False, "model": None, "latency_ms": 12, "error": "AuthenticationError: 401"}

    async def fake_probe(current):
        return found

    monkeypatch.setattr("casus.server.app.probe", fake_probe)
    assert client.post("/api/settings/probe").json() == found
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_server.py -q -k "settings or put or probe or bad_update"`
Expected: FAIL. The routes do not exist: `GET /api/settings` is a 404 (`KeyError: 'api_key'`), `PUT` is a 405.

- [ ] **Step 3: Implement**

In `src/casus/server/app.py`, add to the imports:

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..settings import Settings, SettingsError, merge, probe
```

Add above `create_app`:

```python
class SettingsUpdate(BaseModel):
    """A PUT body. Every field is optional; a secret left empty keeps the stored
    one, and `clear` is the only way to remove a secret."""

    model_config = ConfigDict(extra="forbid")

    endpoint: str | None = None
    api_key: str | None = None
    firecrawl_token: str | None = None
    player_model: str | None = None
    agent_model: str | None = None
    run_concurrency: int | None = None
    source_dirs: list[str] | None = None
    clear: list[Literal["api_key", "firecrawl_token"]] = []
```

Change the signature of `create_app` to the master plan's:

```python
def create_app(
    *, scenarios_dir: pathlib.Path, runs_dir: pathlib.Path, settings: Settings | None = None
) -> FastAPI:
```

and add, just before `return app`:

```python
    # The settings this process runs with. `casus serve` loads and applies them
    # before building the app; a PUT saves, reloads and applies again.
    held: dict[str, Settings | None] = {"settings": settings}

    def current() -> Settings:
        if held["settings"] is None:
            held["settings"] = Settings.load()
        return held["settings"]

    @app.get("/api/settings")
    def get_settings() -> dict:
        return current().public()

    @app.put("/api/settings")
    def put_settings(update: SettingsUpdate) -> dict:
        changes = update.model_dump(exclude={"clear"}, exclude_none=True)
        try:
            merge(current(), changes, update.clear).save()
            fresh = Settings.load()
        except SettingsError as exc:
            raise HTTPException(422, str(exc)) from None
        fresh.apply_to_env()
        held["settings"] = fresh
        return fresh.public()

    @app.post("/api/settings/probe")
    async def probe_settings() -> dict:
        return await probe(current())
```

`probe` is looked up in this module's globals when the route runs, which is what lets the tests replace it with `monkeypatch.setattr("casus.server.app.probe", ...)`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_server.py -q`
Expected: PASS, slice 1's tests and the 11 new ones.

- [ ] **Step 5: Commit**

```bash
git add src/casus/server/app.py tests/test_server.py
git commit -m "feat(server): read, save and probe the settings over /api/settings"
```

---

### Task 6: `casus run` and `casus serve` load and apply the settings

**Files:**
- Modify: `src/casus/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Settings.load`, `Settings.apply_to_env`, `SettingsError`; slice 1's `_serve(args)` and `create_app(..., settings=...)`.
- Produces: a private `_settings()` helper. Both commands exit 2 with `casus: <reason>` when the settings cannot be used (a malformed file, an unreadable `CASUS_API_KEY_FILE`).

lingo reads `BASE_URL` and `API_KEY` when an `LLM` is built, so the settings are applied before either command builds anything: `_run` builds the narrator's engine before `engine.run`, and the server's run manager builds engines per run.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, add to the imports:

```python
import os

import pytest
```

and append:

```python
def test_run_applies_the_settings_before_it_builds_an_engine(monkeypatch, tmp_path):
    from casus import engine
    from casus.settings import Settings, merge

    changes = {"api_key": "sk-cli-test-0123456789", "endpoint": "http://127.0.0.1:9/v1"}
    merge(Settings.load(), changes).save()
    seen = {}

    def fake_run(scenario, **kwargs):
        seen.update(key=os.environ.get("API_KEY"), url=os.environ.get("BASE_URL"))
        state = scenario.initial_state()
        return engine.RunSummary(scenario=scenario.name, seed=1, turns=0, states=[state])

    monkeypatch.setattr(engine, "run", fake_run)
    out = tmp_path / "run.jsonl"
    argv = ["run", str(SCENARIOS / "smoke"), "--no-narrate", "--out", str(out)]
    assert cli.main(argv) == 0
    assert seen == {"key": "sk-cli-test-0123456789", "url": "http://127.0.0.1:9/v1"}


def test_a_broken_config_file_stops_run_with_a_message(monkeypatch, capsys):
    from casus import engine
    from casus.settings import config_path

    config_path().parent.mkdir(parents=True)
    config_path().write_text("endpoint = \n")
    monkeypatch.setattr(engine, "run", lambda *a, **k: pytest.fail("the run started"))
    assert cli.main(["run", str(SCENARIOS / "smoke"), "--no-narrate"]) == 2
    assert "config.toml" in capsys.readouterr().err


def test_serve_applies_the_settings_before_it_starts(monkeypatch):
    from casus.settings import Settings, merge

    merge(Settings.load(), {"api_key": "sk-cli-test-0123456789"}).save()
    seen = {}

    def fake_run(app, host, port, log_level):
        seen.update(key=os.environ.get("API_KEY"), host=host)

    monkeypatch.setattr("uvicorn.run", fake_run)
    assert cli.main(["serve", "--no-open"]) == 0
    assert seen == {"key": "sk-cli-test-0123456789", "host": "127.0.0.1"}


def test_a_broken_config_file_stops_serve_with_a_message(monkeypatch, capsys):
    from casus.settings import config_path

    config_path().parent.mkdir(parents=True)
    config_path().write_text("endpoint = \n")
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("the server started"))
    assert cli.main(["serve", "--no-open"]) == 2
    assert "config.toml" in capsys.readouterr().err


def test_serve_offers_no_way_to_listen_beyond_this_machine():
    """The app has no accounts and shows a settings screen; it serves loopback
    only, and there is deliberately no option to change that."""
    with pytest.raises(SystemExit):
        cli.main(["serve", "--host", "0.0.0.0", "--no-open"])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL on the four settings tests (`seen["key"]` is `None`; a broken file does not stop either command). `test_serve_offers_no_way_to_listen_beyond_this_machine` already passes: it guards slice 1's loopback-only `serve`.

- [ ] **Step 3: Implement**

In `src/casus/cli.py`, add above `_run`:

```python
def _settings():
    """Load the settings and export them for lingo, before anything builds an
    engine. Returns None, having said why, when they cannot be used."""
    from .settings import Settings, SettingsError

    try:
        current = Settings.load()
    except SettingsError as exc:
        print(f"casus: {exc}", file=sys.stderr)
        return None
    current.apply_to_env()
    return current
```

Make the first lines of `_run`:

```python
def _run(args) -> int:
    if _settings() is None:
        return 2
```

In slice 1's `_serve`, replace the `app = create_app(...)` statement with:

```python
    settings = _settings()
    if settings is None:
        return 2
    app = create_app(
        scenarios_dir=pathlib.Path(args.scenarios),
        runs_dir=pathlib.Path(args.runs),
        settings=settings,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/casus/cli.py tests/test_cli.py
git commit -m "feat(cli): run and serve load the settings and hand them to lingo first"
```

---

### Task 7: The settings screen

**Files:**
- Modify: `ui/js/i18n.js`, `ui/js/shell.js`, `ui/css/app.css`
- Test: `tests/browser/test_app.py`

**Interfaces:**
- Consumes: `GET/PUT /api/settings`, `POST /api/settings/probe` (Task 5); `Casus.i18n.t`, `Casus.map.esc`, slice 1's `json()` inside `shell.js`; the fixtures `page` and helpers `serve`, `run_records`, `write_run` from slice 1's `tests/browser/`.
- Produces: a `⚙ Settings` button `#settings-open` in `#topactions`, and a modal `#settings` with one `.set[data-field=<name>]` row per field, inputs `#set-<name>`, `#set-save`, `#set-probe` and a status line `#set-status` (class `ok` or `bad` after a probe). No change to the exported `Casus.shell` object.

The modal is the mockup's (`openSettings()` in `casus-v2.html`), with three differences. The values and origins come from the server. A secret field is an empty password input with a *configured* / *not set* badge and, when configured, a **clear** button that marks the secret for removal on save. Only fields someone changed are sent, so saving the endpoint does not copy a model name inherited from the environment into the file.

- [ ] **Step 1: Write the failing browser tests**

Add at the top of `tests/browser/test_app.py`:

```python
import pytest
from browser_support import run_records, serve, write_run

from casus.settings import Settings, merge

FAKE_KEY = "sk-or-v1-casus-browser-7c21e9a4d05b3f"


@pytest.fixture
def settings_url(tmp_path, monkeypatch):
    """The app with a key saved from the screen, one recorded run, and a probe
    that answers without a network."""

    async def fake_probe(current):
        return {"ok": True, "model": "fake/answered", "latency_ms": 1400, "error": None}

    monkeypatch.setattr("casus.server.app.probe", fake_probe)
    merge(Settings.load(), {"api_key": FAKE_KEY}).save()
    runs = tmp_path / "runs"
    runs.mkdir()
    write_run(runs, "reference-1", run_records(tmp_path))
    url, stop = serve(runs, settings=Settings.load())
    yield url
    stop()


def _open_settings(page, url):
    page.goto(url)
    page.locator("#settings-open").click()
    page.wait_for_selector("#settings")
```

and append:

```python
def test_settings_show_a_configured_key_and_never_its_value(page, settings_url):
    _open_settings(page, settings_url)
    row = page.locator('[data-field="api_key"]')
    assert "configured" in row.inner_text()
    assert "from config.toml" in row.inner_text()
    field = row.locator("input")
    assert field.get_attribute("type") == "password"
    assert field.input_value() == ""
    assert "not set" in page.locator('[data-field="firecrawl_token"]').inner_text()
    assert FAKE_KEY[:12] not in page.content()


def test_test_connection_shows_the_model_that_answered(page, settings_url):
    _open_settings(page, settings_url)
    page.locator("#set-probe").click()
    page.wait_for_selector("#set-status.ok")
    text = page.locator("#set-status").inner_text()
    assert "fake/answered" in text and "1.4 s" in text


def test_saving_a_new_endpoint_keeps_the_key_and_writes_nothing_else(page, settings_url):
    _open_settings(page, settings_url)
    page.locator("#set-endpoint").fill("http://127.0.0.1:1234/v1")
    page.locator("#set-save").click()
    page.wait_for_selector("#set-status:has-text('saved')")
    saved = Settings.load()
    assert saved.endpoint == "http://127.0.0.1:1234/v1"
    assert saved.api_key == FAKE_KEY
    assert saved.origins["player_model"] == "default"
    assert "from config.toml" in page.locator('[data-field="endpoint"]').inner_text()


def test_clear_removes_the_key_on_save(page, settings_url):
    _open_settings(page, settings_url)
    page.locator('[data-clear="api_key"]').click()
    page.locator("#set-save").click()
    page.wait_for_selector("#set-status:has-text('saved')")
    assert "not set" in page.locator('[data-field="api_key"]').inner_text()
    assert Settings.load().api_key is None


def test_keys_typed_in_the_settings_stay_in_the_settings(page, settings_url):
    """The viewer toggles presenter mode on P and the shell leaves a run on
    Esc. Neither may fire while the settings are open."""
    page.goto(settings_url + "#/view/reference-1")
    page.wait_for_selector(".visor")
    page.locator("#settings-open").click()
    page.wait_for_selector("#settings")
    page.locator("#set-probe").click()  # focus on a button, where the viewer would act
    page.keyboard.press("p")
    assert "present" not in (page.locator("body").get_attribute("class") or "")
    page.keyboard.press("Escape")
    assert page.locator("#settings").count() == 0
    assert page.evaluate("location.hash") == "#/view/reference-1"
    assert page.locator(".visor").is_visible()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/browser/test_app.py -q`
Expected: FAIL on the five new tests: `#settings-open` never appears (Playwright times out waiting for it).

- [ ] **Step 3: Add the chrome strings**

In `ui/js/i18n.js`, add to `STRINGS.en`:

```js
      settings: "Settings",
      settings_hint: "Stored in ~/.config/casus/config.toml. Environment variables win over "
        + "the file, and each field says where its value comes from. A secret can be "
        + "written, never read.",
      set_endpoint: "Endpoint", set_api_key: "Provider API key",
      set_firecrawl: "Firecrawl token",
      set_player_model: "Default player model", set_agent_model: "Agent model",
      set_concurrency: "Runs at once", set_sources: "Source folders, one per line",
      configured: "configured", not_set: "not set", paste_new: "paste a new one",
      clear: "clear", will_clear: "cleared on save", from_env: "from the environment:",
      from_config: "from config.toml", from_default: "default", save: "Save", saved: "saved",
      probe: "Test connection", probe_hint: "one cheap call against the saved endpoint",
      calling: "calling…", answered: "answered",
```

and to `STRINGS.es`:

```js
      settings: "Ajustes",
      settings_hint: "Viven en ~/.config/casus/config.toml. Las variables de entorno ganan "
        + "al fichero, y cada campo dice de dónde sale su valor. Un secreto se puede "
        + "escribir, nunca leer.",
      set_endpoint: "Dirección del proveedor", set_api_key: "Clave del proveedor",
      set_firecrawl: "Clave de Firecrawl", set_player_model: "Modelo por defecto",
      set_agent_model: "Modelo de los agentes", set_concurrency: "Corridas a la vez",
      set_sources: "Carpetas de fuentes, una por línea",
      configured: "configurada", not_set: "sin configurar", paste_new: "pegar una nueva",
      clear: "borrar", will_clear: "se borra al guardar", from_env: "desde el entorno:",
      from_config: "desde config.toml", from_default: "valor por defecto", save: "Guardar",
      saved: "guardado", probe: "Probar conexión",
      probe_hint: "una llamada barata contra el proveedor guardado",
      calling: "llamando…", answered: "respondió",
```

- [ ] **Step 4: Add the modal to `ui/js/shell.js`**

Insert this block inside the IIFE, just before `function start() {`:

```js
  // --- settings (slice 5) ----------------------------------------------------
  // A secret travels one way. The modal sends a new value when one is typed and
  // never receives one: the server answers "configured" or "not set". Only the
  // fields someone changed are sent, so saving one value does not copy the
  // others, from the environment or the defaults, into the file.
  const SETTINGS = [
    ["endpoint", "set_endpoint", "text"],
    ["api_key", "set_api_key", "secret"],
    ["firecrawl_token", "set_firecrawl", "secret"],
    ["player_model", "set_player_model", "text"],
    ["agent_model", "set_agent_model", "text"],
    ["run_concurrency", "set_concurrency", "number"],
    ["source_dirs", "set_sources", "lines"],
  ];

  async function send(method, url, body) {
    const r = await fetch(url, {
      method, headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await r.json().catch(() => null);
    if (!r.ok) {
      const d = data && data.detail;
      const reason = Array.isArray(d) ? d.map((x) => x.msg).join("; ") : d;
      throw new Error(reason || `${url} ${r.status}`);
    }
    return data;
  }

  function origin(o) {
    if (o.startsWith("env:")) return `${C.i18n.t("from_env")} ${o.slice(4)}`;
    return C.i18n.t(o === "config" ? "from_config" : "from_default");
  }

  function settingRow([name, key, kind], f) {
    const t = C.i18n.t, id = "set-" + name;
    let input, side = "<span></span>";
    if (kind === "secret") {
      const on = f.value === "configured";
      const clear = on
        ? `<button class="btn small" data-clear="${name}">${esc(t("clear"))}</button>` : "";
      input = `<input class="inp" id="${id}" type="password" autocomplete="off"
        placeholder="${esc(t("paste_new"))}">`;
      side = `<span class="acts"><span class="badge ${on ? "ok" : "warn"}">`
        + `${esc(t(on ? "configured" : "not_set"))}</span>${clear}</span>`;
    } else if (kind === "lines") {
      input = `<textarea class="inp" id="${id}" rows="2">${esc(f.value.join("\n"))}</textarea>`;
    } else {
      input = `<input class="inp" id="${id}" type="${kind}" value="${esc(f.value)}">`;
    }
    return `<div class="set" data-field="${name}"><label for="${id}">${esc(t(key))}</label>`
      + `${input}${side}<div class="from">${esc(origin(f.origin))}</div></div>`;
  }

  function changed(box, shown) {
    const body = { clear: [] };
    for (const [name, , kind] of SETTINGS) {
      const el = box.querySelector("#set-" + name);
      if (kind === "secret") {
        if (el.value) body[name] = el.value;
        if (box.querySelector(`[data-clear="${name}"].on`)) body.clear.push(name);
        continue;
      }
      const value = kind === "lines" ? el.value.split("\n").map((s) => s.trim()).filter(Boolean)
        : kind === "number" ? Number(el.value) : el.value;
      if (JSON.stringify(value) !== JSON.stringify(shown[name].value)) body[name] = value;
    }
    return body;
  }

  function closeSettings() {
    const m = document.getElementById("settings");
    if (m) m.remove();
  }

  async function openSettings(note) {
    const shown = await json("/api/settings");
    const t = C.i18n.t;
    closeSettings();
    document.body.insertAdjacentHTML("beforeend", `<div class="modal" id="settings">
      <div class="box" role="dialog" aria-label="${esc(t("settings"))}">
      <h2>${esc(t("settings"))} <button data-close>×</button></h2>
      <div class="hint">${esc(t("settings_hint"))}</div>
      ${SETTINGS.map((s) => settingRow(s, shown[s[0]])).join("")}
      <div class="acts"><button class="btn primary" id="set-save">${esc(t("save"))}</button>
        <button class="btn" id="set-probe">${esc(t("probe"))}</button>
        <span class="probe" id="set-status">${esc(note || t("probe_hint"))}</span></div>
      </div></div>`);
    const modal = document.getElementById("settings");
    const status = document.getElementById("set-status");
    const say = (cls, text) => {
      status.className = "probe " + cls;
      status.textContent = text;
    };
    // Keys typed here must not step the viewer, present, or leave the screen.
    modal.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Escape") closeSettings();
    });
    modal.addEventListener("click", (e) => {
      if (e.target === modal || e.target.hasAttribute("data-close")) return closeSettings();
      if (e.target.hasAttribute("data-clear")) {
        const on = e.target.classList.toggle("on");
        e.target.textContent = t(on ? "will_clear" : "clear");
      }
    });
    document.getElementById("set-save").onclick = async () => {
      try {
        await send("PUT", "/api/settings", changed(modal, shown));
        await openSettings(t("saved"));
      } catch (err) { say("bad", "✗ " + err.message); }
    };
    document.getElementById("set-probe").onclick = async () => {
      say("", t("calling"));
      try {
        const r = await send("POST", "/api/settings/probe");
        const secs = r.ok ? (r.latency_ms / 1000).toFixed(1) : "";
        if (r.ok) say("ok", `✓ ${t("answered")} ${r.model} · ${secs} s`);
        else say("bad", "✗ " + r.error);
      } catch (err) { say("bad", "✗ " + err.message); }
    };
  }

```

In `start()`, before the `dispatch();` line, add the button:

```js
    const label = esc(C.i18n.t("settings"));
    document.getElementById("topactions").insertAdjacentHTML(
      "beforeend", `<button class="iconbtn" id="settings-open">⚙ ${label}</button>`);
    document.getElementById("settings-open").onclick = () => openSettings();
```

Every server string reaches the page through `esc()` or `textContent`, never raw HTML. The button sits in the `.chrome` top bar, so presenter mode hides it with the rest of the chrome.

- [ ] **Step 5: Add the CSS**

Check the mockup's rules came across in slice 1: `grep -c '^\.modal\|^\.set\b\|^\.set \|^\.probe' ui/css/app.css` should print at least 4. Then append to `ui/css/app.css`:

```css
/* settings (slice 5). .modal, .set, .probe, .inp, .hint and .badge are the mockup's. */
.modal .box{max-height:92vh;overflow:auto}
.modal .acts{align-items:center}
.set textarea.inp{resize:vertical}
.set .acts{margin-top:0;flex-wrap:nowrap;align-items:center}
.set [data-clear].on{color:var(--bad);border-color:var(--bad)}
.probe.bad{color:var(--bad)}
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/browser/test_app.py tests/test_ui_scripts.py -q`
Expected: PASS, including `test_every_ui_script_parses[shell.js]` and `[i18n.js]` (`node --check`).

- [ ] **Step 7: Break it on purpose**

In `shell.js`, delete the line `e.stopPropagation();` in the modal's keydown listener. Run `uv run pytest tests/browser/test_app.py -q -k stay_in_the_settings`. Expected: FAIL (`p` toggles presenter mode, and `Escape` leaves for `#/`). Restore the line.

- [ ] **Step 8: Look at it**

Run `uv run casus serve --no-open` with no settings variables set, open `http://127.0.0.1:8321/`, click **⚙ Settings**. Compare with the mockup's modal: label column, input, badge, origin line under each field, **Save** and **Test connection** on the bottom row.

- [ ] **Step 9: Commit**

```bash
git add ui/js/i18n.js ui/js/shell.js ui/css/app.css tests/browser/test_app.py
git commit -m "feat(ui): the settings screen, secrets write-only, with a connection test"
```

---

### Task 8: Docs, spec status, and the acceptance check

**Files:**
- Modify: `README.md` ("Install and run", a new "Configuration" subsection, the module table), `AGENTS.md` ("What done means"), `docs/specs/2026-09-28-interface-design.md` (status header), `docs/plans/2026-09-29-casus-app-plan.md` (slice table PR number, and the contract additions below)

- [ ] **Step 1: README**

After the paragraph that starts "The transport is [lingo]…" and its Ollama example, add:

````markdown
### Configuration

casus reads `~/.config/casus/config.toml` (under `$XDG_CONFIG_HOME` when that is
set). The settings screen in `casus serve` writes it, readable by you only. An
environment variable wins over the file, and the screen says which one is in
effect for each field.

| setting | variables, first wins | default |
|---|---|---|
| endpoint | `CASUS_ENDPOINT`, `BASE_URL` | `https://openrouter.ai/api/v1` |
| provider key | `CASUS_API_KEY`, `CASUS_API_KEY_FILE` (a file with the key), `API_KEY` | none |
| Firecrawl token | `FIRECRAWL_API_KEY` | none |
| default player model | `CASUS_PLAYER_MODEL` | `qwen/qwen3-32b` |
| agent model | `CASUS_AGENT_MODEL` | `qwen/qwen3-32b` |
| runs at once | `CASUS_RUN_CONCURRENCY` | 4 |
| source folders | `CASUS_SOURCE_DIRS` (`:`-separated) | none |

The screen never shows a key, only whether one is set, and **Test connection**
makes one short call and reports the model that answered. A key is never
written to a transcript or a bundle; `tests/test_settings.py` checks both.

```bash
CASUS_API_KEY_FILE=~/.config/openrouter.token uv run casus run scenarios/smoke --turns 1
```
````

Add a row to the module table: `settings.py` | "Where each setting comes from, the config file, handing the key to lingo, and the connection probe".

- [ ] **Step 2: AGENTS.md**

Under "What done means", add to the checks a person runs:

```markdown
- `uv run casus serve`, open ⚙ Settings, press **Test connection**: it names the
  model that answered, or the error, and never shows the key.
```

- [ ] **Step 3: Spec status and the master plan**

In `docs/specs/2026-09-28-interface-design.md` frontmatter, add slice 5 to the `status:` line with its PR number, keeping the slices already listed.

In `docs/plans/2026-09-29-casus-app-plan.md`, fill the PR number into slice 5's row and apply the additions listed under "Contract changes needed" at the end of this plan.

- [ ] **Step 4: Acceptance, the way a person does it**

Use a throwaway config directory, so the acceptance does not leave a new key file on this machine without Alex asking for one:

```bash
export XDG_CONFIG_HOME=$(mktemp -d)
env -u API_KEY -u BASE_URL \
  CASUS_API_KEY_FILE=/home/apiad/Workspace/.claude/openrouter.token uv run casus serve
```

In the browser:

1. **⚙ Settings**: the provider key reads *configured*, *from the environment: CASUS_API_KEY_FILE*; the endpoint reads *default*. No key characters anywhere on the screen.
2. **Test connection**: `✓ answered qwen/qwen3-32b · N s` with a real model name and latency.
3. Stop the server and start it again without `CASUS_API_KEY_FILE` (`env -u API_KEY -u BASE_URL uv run casus serve`). The key reads *not set*. Paste the key, **Save**: it reads *configured*, *from config.toml*. Then `stat -c %a "$XDG_CONFIG_HOME/casus/config.toml"` prints `600`.
4. Paste `sk-or-v1-wrong-000000000000`, **Save**, **Test connection**: a `✗ AuthenticationError: …401…` line that does not contain `sk-or-v1-wro`. Paste the real key again and **Save**.
5. Press `P` on a recorded run: the settings button hides with the rest of the chrome.

Then a real run whose key comes from the file alone, and the grep the leak test does, on real output:

```bash
env -u API_KEY -u BASE_URL uv run casus run scenarios/smoke --turns 1 --no-narrate \
  --out /tmp/accept-5.jsonl
uv run casus bundle /tmp/accept-5.jsonl --out /tmp/accept-5.html
grep -c -F "$(head -c 12 /home/apiad/Workspace/.claude/openrouter.token)" \
  /tmp/accept-5.jsonl /tmp/accept-5.html
```

Expected: the run completes, and `grep` prints `0` for both files (its exit code is 1, which here is the pass). Note in the PR body what was checked, against which endpoint and model.

- [ ] **Step 5: Flag, do not fix, the class README**

`vault/Efforts/Areas/University/casus-clase/README.md` documents `CASUS_API_KEY_FILE`, which this slice makes real. Its run command still names `scenarios/private/caribbean-2026.yaml`, the v1 single-file layout, where v2 takes a scenario directory. Say so in the PR body for Alex; the vault is not edited from this repo's PR.

- [ ] **Step 6: Commit and open the PR**

```bash
git add README.md AGENTS.md docs/specs/2026-09-28-interface-design.md \
  docs/plans/2026-09-29-casus-app-plan.md
git commit -m "docs: settings, the variables casus reads, and how to check a connection"
git push -u origin 5-slice-5-settings
gh pr create --title "feat: settings, with write-only secrets and a connection test" \
  --body "Part of #5. ..."
```

---

## Contract changes needed

> Applied during plan review (2026-09-29) to the master plan's "Amendments from the slice plans" section, resolved against the other slices. Do not edit the master plan again for these; if the code must differ from the amendments, change the amendments in this slice's PR.

No existing name changes. Additions for the master plan, applied in Task 8 Step 3:

1. **`settings.py` public names beyond `Settings` and `probe`:** `SettingsError`, `config_path(env=None) -> Path`, `merge(current, changes, clear=()) -> Settings`, `redact(text, secrets=None) -> str`, and the constants `FIELDS`, `SECRETS`, `ENV`, `DEFAULTS`, `EXPORTED`. Slices 6 and 7 should call `redact()` on any exception text they show or record, and read `settings.firecrawl_token` / `agent_model` / `source_dirs` / `run_concurrency` from `Settings.load()` rather than the environment.
2. **`apply_to_env()` also exports `FIRECRAWL_API_KEY`**, besides `BASE_URL` and `API_KEY`. The master plan's comment says "sets BASE_URL / API_KEY for lingo".
3. **`Settings.public()` shape:** `{field: {"value", "origin", "secret"}}`, a secret's value being `"configured"` or `"not set"`. `GET /api/settings` returns it as is.
4. **`PUT /api/settings` body:** any subset of the fields, plus `clear: ["api_key" | "firecrawl_token"]`. An empty secret keeps the stored one; unknown fields and bad values are a 422 and change nothing. The response is the reloaded `public()`.
5. **Slice 3's `engine._error_text`** returns its text through `settings.redact()`, so an `error` record never quotes a key a provider echoed back. Task 4 Step 3 makes the change when slice 3 is already on `main`; if slice 5 lands first, `tests/test_settings.py::test_a_run_whose_key_is_rejected_leaves_no_trace` fails in slice 3's PR until slice 3 makes it. `test_a_live_run_whose_key_is_rejected_leaves_no_trace` skips until `casus.server.runs` exists.
6. **File-structure table:** `cli.py` gains "5: `run` and `serve` load and apply settings"; `ui/js/i18n.js` gains "5: settings strings"; `ui/css/app.css` gains "5: settings rules". The table lists those files for slice 1 only, and it says a later slice modifies an earlier slice's file only where the table says so.
