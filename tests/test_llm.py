import json

import pytest

from casus import llm


class _FakeResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> dict:
        return self._body


def _cfg(**overrides) -> llm.Config:
    base = dict(
        base_url="http://localhost:1234/v1",
        api_key="x",
        default_model="qwen/qwen3-32b",
        timeout_s=30.0,
        retry_wait_s=0.0,
    )
    base.update(overrides)
    return llm.Config(**base)


def _ok_body(content: str = '{"ok": true}') -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3},
        "model": "qwen/qwen3-32b",
    }


def test_complete_posts_to_configured_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs, url=url)
        return _FakeResponse(200, _ok_body())

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    result = llm.complete(
        "qwen/qwen3-32b", [{"role": "user", "content": "hi"}], config=_cfg()
    )

    assert captured["json"]["messages"][0]["content"] == "hi"
    assert captured["headers"]["Authorization"] == "Bearer x"
    assert result.text == '{"ok": true}'
    assert result.prompt_tokens == 11
    assert result.completion_tokens == 3


def test_complete_targets_the_chat_completions_path(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        return _FakeResponse(200, _ok_body())

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    llm.complete("m", [{"role": "user", "content": "x"}], config=_cfg())
    assert seen["url"] == "http://localhost:1234/v1/chat/completions"


def test_schema_is_passed_as_json_schema_response_format(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(200, _ok_body())

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    llm.complete(
        "m",
        [{"role": "user", "content": "x"}],
        schema={"type": "object"},
        config=_cfg(),
    )
    fmt = captured["json"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["schema"] == {"type": "object"}


def test_no_authorization_header_when_the_key_is_empty(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(200, _ok_body())

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    llm.complete("m", [{"role": "user", "content": "x"}], config=_cfg(api_key=""))
    assert "Authorization" not in captured["headers"]


def test_complete_raises_llm_error_on_http_500(monkeypatch):
    monkeypatch.setattr(
        llm.httpx, "post", lambda url, **kw: _FakeResponse(500, {"error": "boom"})
    )
    with pytest.raises(llm.LLMError, match="HTTP 500"):
        llm.complete("m", [{"role": "user", "content": "x"}], config=_cfg())


def test_retryable_status_is_retried_exactly_once(monkeypatch):
    attempts = []

    def flaky(url, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            return _FakeResponse(429, {"error": "slow down"})
        return _FakeResponse(200, _ok_body("second try"))

    monkeypatch.setattr(llm.httpx, "post", flaky)
    result = llm.complete("m", [{"role": "user", "content": "x"}], config=_cfg())
    assert len(attempts) == 2
    assert result.text == "second try"


def test_non_retryable_status_is_not_retried(monkeypatch):
    attempts = []

    def unauthorized(url, **kwargs):
        attempts.append(1)
        return _FakeResponse(401, {"error": "nope"})

    monkeypatch.setattr(llm.httpx, "post", unauthorized)
    with pytest.raises(llm.LLMError, match="HTTP 401"):
        llm.complete("m", [{"role": "user", "content": "x"}], config=_cfg())
    assert len(attempts) == 1, "a 401 will never succeed on retry"


def test_transport_error_becomes_llm_error(monkeypatch):
    def explode(url, **kwargs):
        raise llm.httpx.ConnectError("no route")

    monkeypatch.setattr(llm.httpx, "post", explode)
    with pytest.raises(llm.LLMError, match="transport error"):
        llm.complete("m", [{"role": "user", "content": "x"}], config=_cfg())


def test_a_bug_in_the_request_path_is_not_disguised_as_a_transport_error(monkeypatch):
    """The wide `except Exception` this replaces reported argument bugs as network
    failures, which is how a broken request path ships looking healthy."""

    def wrong_signature():
        return None

    monkeypatch.setattr(llm.httpx, "post", wrong_signature)
    with pytest.raises(TypeError):
        llm.complete("m", [{"role": "user", "content": "x"}], config=_cfg())


def test_missing_message_content_is_an_llm_error_not_a_key_error(monkeypatch):
    monkeypatch.setattr(
        llm.httpx, "post", lambda url, **kw: _FakeResponse(200, {"choices": []})
    )
    with pytest.raises(llm.LLMError, match="no message content"):
        llm.complete("m", [{"role": "user", "content": "x"}], config=_cfg())


def test_config_from_env_reads_the_key_file(monkeypatch, tmp_path):
    key_file = tmp_path / "token"
    key_file.write_text("sk-from-file\n")
    monkeypatch.delenv("CASUS_API_KEY", raising=False)
    monkeypatch.setenv("CASUS_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("CASUS_BASE_URL", "http://example.test/v1/")
    cfg = llm.Config.from_env()
    assert cfg.api_key == "sk-from-file"
    assert cfg.base_url == "http://example.test/v1", "trailing slash must be stripped"


def test_config_from_env_prefers_the_inline_key(monkeypatch, tmp_path):
    key_file = tmp_path / "token"
    key_file.write_text("sk-from-file")
    monkeypatch.setenv("CASUS_API_KEY", "sk-inline")
    monkeypatch.setenv("CASUS_API_KEY_FILE", str(key_file))
    assert llm.Config.from_env().api_key == "sk-inline"
