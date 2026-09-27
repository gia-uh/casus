"""One function against any OpenAI-compatible chat-completions endpoint.

This is the only module in the package that touches the network. `rules.py` is
tested to import nothing from here, which is what keeps the numbers auditable.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import time

import httpx

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "qwen/qwen3-32b"
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})


class LLMError(RuntimeError):
    """Transport failure, HTTP error, or a response missing its content."""


@dataclasses.dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    default_model: str = DEFAULT_MODEL
    timeout_s: float = 120.0
    retry_wait_s: float = 2.0

    @classmethod
    def from_env(cls) -> Config:
        """Read configuration from the environment.

        `CASUS_API_KEY` wins; failing that `CASUS_API_KEY_FILE` is read from
        disk, so a key never has to appear in a shell history or a scenario file.
        A local endpoint (LM Studio, Ollama) usually needs no key at all, so an
        empty string is legal.
        """
        key = os.environ.get("CASUS_API_KEY", "")
        if not key:
            key_file = os.environ.get("CASUS_API_KEY_FILE", "")
            if key_file:
                key = pathlib.Path(key_file).expanduser().read_text().strip()
        return cls(
            base_url=os.environ.get("CASUS_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            api_key=key,
            default_model=os.environ.get("CASUS_MODEL", DEFAULT_MODEL),
            timeout_s=float(os.environ.get("CASUS_TIMEOUT_S", "120")),
        )


@dataclasses.dataclass(frozen=True)
class LLMResult:
    text: str
    raw: dict
    model: str
    prompt_tokens: int
    completion_tokens: int


def complete(
    model: str,
    messages: list[dict],
    schema: dict | None = None,
    temperature: float = 0.7,
    config: Config | None = None,
) -> LLMResult:
    """Send one chat completion and return its text.

    `schema` is passed as a JSON-schema response format when the backend
    supports it. Backends that ignore it still work, because every caller
    validates the returned JSON itself rather than trusting the server.
    """
    cfg = config or Config.from_env()
    payload: dict = {
        "model": model or cfg.default_model,
        "messages": messages,
        "temperature": temperature,
    }
    if schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "action_declaration", "strict": True, "schema": schema},
        }

    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    url = f"{cfg.base_url}/chat/completions"
    last_error = ""
    for attempt in (1, 2):
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=cfg.timeout_s)
        except httpx.HTTPError as exc:
            # Only transport-level failures are retried. Anything else — a bug in
            # this module, a wrong argument — must surface, not read as a network
            # hiccup.
            last_error = f"transport error: {type(exc).__name__}: {exc}"
        else:
            if response.status_code == 200:
                return _parse(response.json(), payload["model"])
            last_error = f"HTTP {response.status_code}: {_body_excerpt(response)}"
            if response.status_code not in RETRYABLE_STATUS:
                break
        if attempt == 1 and cfg.retry_wait_s:
            time.sleep(cfg.retry_wait_s)
    raise LLMError(f"{url} failed after retry — {last_error}")


def _parse(body: dict, model: str) -> LLMResult:
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"response has no message content: {json.dumps(body)[:300]}") from exc
    if text is None:
        raise LLMError("response message content was null")
    usage = body.get("usage") or {}
    return LLMResult(
        text=text,
        raw=body,
        model=body.get("model", model),
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
    )


def _body_excerpt(response) -> str:
    """Best-effort excerpt of an error body, for the message in LLMError."""
    try:
        return json.dumps(response.json())[:200]
    except (ValueError, TypeError, AttributeError):
        return str(getattr(response, "text", ""))[:200]


def _smoke() -> int:
    """Manual check against the real endpoint. Not part of the test suite."""
    cfg = Config.from_env()
    print(
        f"base_url={cfg.base_url} model={cfg.default_model} key={'set' if cfg.api_key else 'none'}"
    )
    result = complete(
        cfg.default_model,
        [{"role": "user", "content": "Reply with exactly: casus online"}],
        temperature=0.0,
        config=cfg,
    )
    print(f"model={result.model} tokens={result.prompt_tokens}/{result.completion_tokens}")
    print(f"text={result.text.strip()[:200]!r}")
    return 0


if __name__ == "__main__":
    import sys

    if "--smoke" in sys.argv:
        raise SystemExit(_smoke())
    print("usage: python -m casus.llm --smoke")
