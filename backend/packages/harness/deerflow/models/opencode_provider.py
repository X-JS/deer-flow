"""OpenCode Go (Zen) chat model with a per-thread session header.

The OpenCode Go endpoint (``https://opencode.ai/zen/go/v1``) routes requests by
session and rejects one that omits ``x-opencode-session`` with HTTP 400
``MissingSessionID``. It also recommends a *stable* session id per conversation
so routing and prompt caching work well.

DeerFlow binds ``thread_id`` into the LangGraph runnable config, so this provider
resolves the current thread on every request and sends it as a per-request
header. The OpenAI SDK merges ``extra_headers`` over ``default_headers``
(second mapping wins), so the dynamic value transparently overrides a static
``x-opencode-session`` set in ``config.yaml``.

Usage in ``config.yaml``::

    - name: deepseek-v4-flash
      display_name: OpenCode Go (Zen) / deepseek-v4-flash
      use: deerflow.models.opencode_provider:OpenCodeChatModel
      model: deepseek-v4-flash
      api_key: $OPENCODE_API_KEY
      base_url: https://opencode.ai/zen/go/v1
      default_headers:
        User-Agent: deer-flow/1.0
        # Fallback for calls with no thread context (title generation, memory
        # extraction, ad-hoc probes). Threaded requests send "deer-flow:<thread_id>".
        x-opencode-session: deer-flow
      supports_thinking: true
"""

from __future__ import annotations

import logging
from typing import Any, Final

from langchain_core.language_models import LanguageModelInput
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

SESSION_HEADER: Final[str] = "x-opencode-session"
SESSION_PREFIX: Final[str] = "deer-flow:"
_FALLBACK_SESSION: Final[str] = "deer-flow"
# Printable-ASCII cap for the thread-derived part; keeps the value header-safe.
_MAX_SESSION_ID_LEN: Final[int] = 128


def _normalize_session_id(value: object) -> str | None:
    """Return a header-safe thread id, or ``None`` when *value* is unusable.

    Only printable ASCII (0x20-0x7E) is accepted: header values with CR/LF or
    non-latin-1 codepoints would break the HTTP layer, and a value longer than
    :data:`_MAX_SESSION_ID_LEN` is rejected rather than truncated (a truncated
    id could collide with another thread's session).
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > _MAX_SESSION_ID_LEN:
        return None
    if any(ord(ch) < 32 or ord(ch) > 126 for ch in cleaned):
        return None
    return cleaned


def _current_thread_id() -> str | None:
    """Return the current LangGraph ``thread_id``, or ``None`` outside a run.

    ``langgraph.config.get_config()`` reads the active runnable config; it raises
    ``RuntimeError`` when called outside a runnable (title generation, memory
    extraction, ad-hoc ``model.invoke``), which callers treat as "no thread".
    """
    try:
        from langgraph.config import get_config

        config = get_config()
    except RuntimeError:
        return None
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if isinstance(configurable, dict):
        thread_id = configurable.get("thread_id")
        if thread_id:
            return thread_id
    metadata = config.get("metadata")
    if isinstance(metadata, dict):
        thread_id = metadata.get("thread_id")
        if thread_id:
            return thread_id
    return None


class OpenCodeChatModel(ChatOpenAI):
    """``ChatOpenAI`` that sends a per-thread ``x-opencode-session`` header."""

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Add ``x-opencode-session`` to the per-request headers.

        Injected in the payload (not the client), so one model instance can be
        reused across threads and every sync/async/streaming/responses call
        picks up the right value through the single ``_get_request_payload``
        choke point.
        """
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        session = self._resolve_session()
        if session:
            headers = dict(payload.get("extra_headers") or {})
            headers[SESSION_HEADER] = session
            payload["extra_headers"] = headers
        return payload

    def _resolve_session(self) -> str:
        """Thread-scoped session when available, else the configured fallback."""
        thread_id = _normalize_session_id(_current_thread_id())
        if thread_id:
            session = f"{SESSION_PREFIX}{thread_id}"
            logger.debug("OpenCode Go %s=%s (thread-scoped)", SESSION_HEADER, session)
            return session
        headers = self.default_headers or {}
        session = str(headers.get(SESSION_HEADER) or _FALLBACK_SESSION)
        logger.debug("OpenCode Go %s=%s (fallback, no thread context)", SESSION_HEADER, session)
        return session
