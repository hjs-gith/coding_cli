"""Thin client for Dify's chat-messages API.

Wraps ``POST {base_url}/chat-messages`` in both streaming (SSE) and blocking
modes, and persists ``conversation_id`` so the Dify backend keeps history across
turns of the agentic loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import requests


class DifyError(RuntimeError):
    """Raised when the Dify API returns an error or an unexpected response."""


@dataclass
class ChatResult:
    """The outcome of a single chat-messages call."""

    answer: str
    conversation_id: str
    message_id: str


class DifyClient:
    """Client that holds conversation state for one CLI session."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        user_id: str,
        timeout: int = 120,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id
        self.timeout = timeout
        self.conversation_id: str = ""
        self._session = requests.Session()

    def reset(self) -> None:
        """Start a fresh Dify conversation on the next call."""
        self.conversation_id = ""

    # -- public API ----------------------------------------------------------

    def chat(self, query: str, stream: bool = True, on_delta=None) -> ChatResult:
        """Send ``query`` and return the model's answer.

        Updates ``self.conversation_id`` from the response so subsequent calls
        continue the same conversation. When streaming, ``on_delta`` (if given)
        is called with each incremental piece of answer text as it arrives.
        """
        if stream:
            return self._chat_streaming(query, on_delta)
        return self._chat_blocking(query)

    # -- internals -----------------------------------------------------------

    @property
    def _url(self) -> str:
        return f"{self.base_url}/chat-messages"

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _body(self, query: str, response_mode: str) -> dict:
        return {
            "query": query,
            "inputs": {},
            "response_mode": response_mode,
            "user": self.user_id,
            "conversation_id": self.conversation_id,
        }

    def _chat_blocking(self, query: str) -> ChatResult:
        try:
            resp = self._session.post(
                self._url,
                headers=self._headers,
                json=self._body(query, "blocking"),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DifyError(f"Request to Dify failed: {exc}") from exc
        if resp.status_code >= 400:
            raise DifyError(_format_http_error(resp))
        try:
            data = resp.json()
        except ValueError as exc:
            raise DifyError(f"Invalid JSON from Dify: {exc}") from exc
        result = ChatResult(
            answer=data.get("answer", ""),
            conversation_id=data.get("conversation_id", self.conversation_id),
            message_id=data.get("message_id", ""),
        )
        if result.conversation_id:
            self.conversation_id = result.conversation_id
        return result

    def _chat_streaming(self, query: str, on_delta=None) -> ChatResult:
        try:
            resp = self._session.post(
                self._url,
                headers=self._headers,
                json=self._body(query, "streaming"),
                timeout=self.timeout,
                stream=True,
            )
        except requests.RequestException as exc:
            raise DifyError(f"Request to Dify failed: {exc}") from exc
        if resp.status_code >= 400:
            raise DifyError(_format_http_error(resp))

        answer_parts: list[str] = []
        conversation_id = self.conversation_id
        message_id = ""
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            payload = raw_line[len("data:") :].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            etype = event.get("event")
            if etype in ("message", "agent_message"):
                delta = event.get("answer", "")
                answer_parts.append(delta)
                if on_delta is not None and delta:
                    on_delta(delta)
            elif etype == "error":
                raise DifyError(
                    f"Dify stream error: {event.get('message') or event}"
                )
            if event.get("conversation_id"):
                conversation_id = event["conversation_id"]
            if event.get("message_id"):
                message_id = event["message_id"]

        if conversation_id:
            self.conversation_id = conversation_id
        return ChatResult(
            answer="".join(answer_parts),
            conversation_id=conversation_id,
            message_id=message_id,
        )


def _format_http_error(resp: "requests.Response") -> str:
    detail = resp.text
    try:
        body = resp.json()
        detail = body.get("message") or body.get("code") or detail
    except ValueError:
        pass
    return f"Dify API error {resp.status_code}: {detail}"
