"""Thin client for Dify's chat-messages API.

Wraps ``POST {base_url}/chat-messages`` in both streaming (SSE) and blocking
modes, and persists ``conversation_id`` so the Dify backend keeps history across
turns of the agentic loop.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests


def _debug(label: str, payload) -> None:
    """Print request/response detail to stderr when CODING_CLI_DEBUG is set."""
    if os.environ.get("CODING_CLI_DEBUG"):
        print(f"[dify:{label}] {payload}", file=sys.stderr, flush=True)

# Image attachments (Dify vision input). Dify accepts these for image files;
# the app itself must have Vision enabled for the model to actually see them.
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


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
        self._parameters: Optional[dict] = None  # cached GET /parameters

    def reset(self) -> None:
        """Start a fresh Dify conversation on the next call."""
        self.conversation_id = ""

    # -- public API ----------------------------------------------------------

    def chat(
        self,
        query: str,
        stream: bool = True,
        on_delta=None,
        files: "Optional[list[dict]]" = None,
    ) -> ChatResult:
        """Send ``query`` and return the model's answer.

        Updates ``self.conversation_id`` from the response so subsequent calls
        continue the same conversation. When streaming, ``on_delta`` (if given)
        is called with each incremental piece of answer text as it arrives.
        ``files`` carries attachment descriptors (see ``image_file``) for vision
        input; it is omitted from the request entirely when empty.
        """
        if stream:
            return self._chat_streaming(query, on_delta, files)
        return self._chat_blocking(query, files)

    def app_parameters(self) -> dict:
        """Fetch (and cache) the Dify app's published parameters.

        Used to tell the user up front whether the app accepts image uploads at
        all. Any failure caches an empty dict so this never blocks a turn.
        """
        if self._parameters is None:
            try:
                resp = self._session.get(
                    f"{self.base_url}/parameters",
                    headers=self._auth_headers,
                    params={"user": self.user_id},
                    timeout=self.timeout,
                )
                self._parameters = resp.json() if resp.status_code < 400 else {}
            except (requests.RequestException, ValueError):
                self._parameters = {}
            _debug("parameters", self._parameters)
        return self._parameters

    def image_upload_enabled(self) -> Optional[bool]:
        """Whether the app accepts image uploads: True/False, or None if unknown.

        Handles both the ``file_upload.image.enabled`` shape and the newer
        ``file_upload.enabled`` + ``allowed_file_types`` shape. ``None`` means the
        app did not say, so callers should not warn.
        """
        upload = self.app_parameters().get("file_upload")
        if not isinstance(upload, dict):
            return None
        image = upload.get("image")
        if isinstance(image, dict) and "enabled" in image:
            return bool(image["enabled"])
        if "enabled" in upload:
            if not upload["enabled"]:
                return False
            types = upload.get("allowed_file_types") or []
            return (not types) or ("image" in types)
        return None

    def upload_file(self, path: "Path | str") -> str:
        """Upload a local image to Dify and return its file id.

        The id is passed back in a ``chat`` ``files`` entry. Raises ``DifyError``
        for an unsupported extension, an oversized file, or an API failure.
        """
        target = Path(path)
        if not target.is_file():
            raise DifyError(f"No such file: {target}")
        suffix = target.suffix.lower()
        if suffix not in IMAGE_EXTS:
            raise DifyError(
                f"Unsupported image type '{suffix or target.name}'. "
                f"Supported: {', '.join(sorted(IMAGE_EXTS))}."
            )
        size = target.stat().st_size
        if size > MAX_IMAGE_BYTES:
            raise DifyError(
                f"{target.name} is {size / 1_048_576:.1f} MB; the limit is "
                f"{MAX_IMAGE_BYTES // 1_048_576} MB."
            )
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        try:
            with target.open("rb") as fh:
                resp = self._session.post(
                    f"{self.base_url}/files/upload",
                    headers=self._auth_headers,  # no JSON content-type: multipart
                    files={"file": (target.name, fh, mime)},
                    data={"user": self.user_id},
                    timeout=self.timeout,
                )
        except requests.RequestException as exc:
            raise DifyError(f"Upload to Dify failed: {exc}") from exc
        except OSError as exc:
            raise DifyError(f"Could not read {target}: {exc}") from exc
        if resp.status_code >= 400:
            detail = _format_http_error(resp)
            if resp.status_code in (400, 403):
                detail += (
                    " — the Dify app may not have Vision enabled, or the file "
                    "type is not permitted for this app."
                )
            raise DifyError(detail)
        try:
            data = resp.json()
        except ValueError as exc:
            raise DifyError(f"Invalid JSON from Dify upload: {exc}") from exc
        _debug("upload", data)
        file_id = data.get("id")
        if not file_id:
            raise DifyError(f"Dify upload returned no file id: {data}")
        return file_id

    # -- internals -----------------------------------------------------------

    @property
    def _url(self) -> str:
        return f"{self.base_url}/chat-messages"

    @property
    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    @property
    def _headers(self) -> dict:
        return {**self._auth_headers, "Content-Type": "application/json"}

    def _body(
        self,
        query: str,
        response_mode: str,
        files: "Optional[list[dict]]" = None,
    ) -> dict:
        body = {
            "query": query,
            "inputs": {},
            "response_mode": response_mode,
            "user": self.user_id,
            "conversation_id": self.conversation_id,
        }
        if files:  # omit entirely when unused, keeping the plain request shape
            body["files"] = list(files)
            _debug("chat.files", body["files"])
        return body

    def _chat_blocking(
        self, query: str, files: "Optional[list[dict]]" = None
    ) -> ChatResult:
        try:
            resp = self._session.post(
                self._url,
                headers=self._headers,
                json=self._body(query, "blocking", files),
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

    def _chat_streaming(
        self, query: str, on_delta=None, files: "Optional[list[dict]]" = None
    ) -> ChatResult:
        try:
            resp = self._session.post(
                self._url,
                headers=self._headers,
                json=self._body(query, "streaming", files),
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


def image_file(upload_file_id: str) -> dict:
    """Build a chat ``files`` entry for an already-uploaded image."""
    return {
        "type": "image",
        "transfer_method": "local_file",
        "upload_file_id": upload_file_id,
    }


def _format_http_error(resp: "requests.Response") -> str:
    detail = resp.text
    try:
        body = resp.json()
        detail = body.get("message") or body.get("code") or detail
    except ValueError:
        pass
    return f"Dify API error {resp.status_code}: {detail}"
