"""Tests for the per-thread ``x-opencode-session`` header injection.

OpenCode Go (Zen) routes requests by session and rejects a request that omits
``x-opencode-session`` (400 MissingSessionID). DeerFlow binds ``thread_id`` into
the LangGraph runnable config, so the provider resolves it per request and sends
it as a per-request header, overriding any static ``default_headers`` value.
"""

from __future__ import annotations

import langchain_openai
from langchain_core.messages import HumanMessage

from deerflow.models.opencode_provider import (
    SESSION_HEADER,
    SESSION_PREFIX,
    OpenCodeChatModel,
    _normalize_session_id,
)


def _make_model(**kwargs) -> OpenCodeChatModel:
    return OpenCodeChatModel(
        model="deepseek-v4-flash",
        api_key="test-key",
        base_url="http://localhost:1/v1",
        **kwargs,
    )


def _config(thread_id=None, *, in_metadata=False):
    if thread_id is None:
        return {"configurable": {}}
    if in_metadata:
        return {"configurable": {}, "metadata": {"thread_id": thread_id}}
    return {"configurable": {"thread_id": thread_id}}


def _patch_config(monkeypatch, config=None, *, raises=False):
    import langgraph.config as langgraph_config

    if raises:

        def _raise():
            raise RuntimeError("no runnable context")

        monkeypatch.setattr(langgraph_config, "get_config", _raise)
    else:
        monkeypatch.setattr(langgraph_config, "get_config", lambda: config)


def test_is_a_chat_openai_subclass():
    assert issubclass(OpenCodeChatModel, langchain_openai.ChatOpenAI)


def test_injects_prefixed_thread_id(monkeypatch):
    _patch_config(monkeypatch, _config("abc-123"))
    payload = _make_model()._get_request_payload([HumanMessage("hi")])

    assert payload["extra_headers"][SESSION_HEADER] == f"{SESSION_PREFIX}abc-123"


def test_session_is_stable_within_a_thread(monkeypatch):
    _patch_config(monkeypatch, _config("thread-1"))
    model = _make_model()

    first = model._get_request_payload([HumanMessage("hi")])["extra_headers"]
    second = model._get_request_payload([HumanMessage("hi again")])["extra_headers"]

    assert first[SESSION_HEADER] == second[SESSION_HEADER]


def test_session_differs_across_threads(monkeypatch):
    model = _make_model()

    _patch_config(monkeypatch, _config("thread-1"))
    a = model._get_request_payload([HumanMessage("hi")])["extra_headers"]
    _patch_config(monkeypatch, _config("thread-2"))
    b = model._get_request_payload([HumanMessage("hi")])["extra_headers"]

    assert a[SESSION_HEADER] != b[SESSION_HEADER]


def test_reads_thread_id_from_metadata_when_configurable_missing(monkeypatch):
    _patch_config(monkeypatch, _config("meta-thread", in_metadata=True))
    payload = _make_model()._get_request_payload([HumanMessage("hi")])

    assert payload["extra_headers"][SESSION_HEADER] == f"{SESSION_PREFIX}meta-thread"


def test_dynamic_session_overrides_static_default_headers(monkeypatch):
    _patch_config(monkeypatch, _config("thread-1"))
    model = _make_model(default_headers={SESSION_HEADER: "static-value"})
    payload = model._get_request_payload([HumanMessage("hi")])

    assert payload["extra_headers"][SESSION_HEADER] == f"{SESSION_PREFIX}thread-1"


def test_falls_back_to_static_default_headers_without_runnable(monkeypatch):
    _patch_config(monkeypatch, raises=True)
    model = _make_model(default_headers={SESSION_HEADER: "static-value"})
    payload = model._get_request_payload([HumanMessage("hi")])

    assert payload["extra_headers"][SESSION_HEADER] == "static-value"


def test_falls_back_to_constant_without_runnable_or_static(monkeypatch):
    _patch_config(monkeypatch, raises=True)
    payload = _make_model()._get_request_payload([HumanMessage("hi")])

    assert payload["extra_headers"][SESSION_HEADER] == "deer-flow"


def test_rejects_control_characters_in_thread_id(monkeypatch):
    _patch_config(monkeypatch, _config("bad\r\nvalue"))
    model = _make_model(default_headers={SESSION_HEADER: "static-value"})
    payload = model._get_request_payload([HumanMessage("hi")])

    assert payload["extra_headers"][SESSION_HEADER] == "static-value"


def test_preserves_other_extra_headers(monkeypatch):
    _patch_config(monkeypatch, _config("thread-1"))
    payload = _make_model()._get_request_payload([HumanMessage("hi")])

    # The thread request should not clobber unrelated per-request headers.
    assert SESSION_HEADER in payload["extra_headers"]


def test_logs_resolved_session_at_debug(monkeypatch, caplog):
    import logging

    _patch_config(monkeypatch, _config("t-9"))
    model = _make_model()

    with caplog.at_level(logging.DEBUG, logger="deerflow.models.opencode_provider"):
        model._get_request_payload([HumanMessage("hi")])

    assert any(f"{SESSION_PREFIX}t-9" in record.getMessage() for record in caplog.records)


# --- _normalize_session_id -------------------------------------------------


def test_normalize_strips_and_caps():
    assert _normalize_session_id("  thread-1  ") == "thread-1"
    assert _normalize_session_id("a" * 500) is None


def test_normalize_rejects_control_and_non_ascii():
    assert _normalize_session_id("line\nbreak") is None
    assert _normalize_session_id("emoji-\U0001f600") is None
    assert _normalize_session_id("") is None
    assert _normalize_session_id(None) is None
