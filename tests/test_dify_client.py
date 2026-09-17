import json

import pytest

from coding_cli import dify_client
from coding_cli.dify_client import DifyClient, DifyError, image_file


class _FakeResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self, decode_unicode=True):
        for line in self._lines:
            yield line


def _sse(event):
    return "data: " + json.dumps(event)


def test_streaming_invokes_on_delta_and_assembles(monkeypatch):
    client = DifyClient(api_key="k", base_url="http://x/v1", user_id="u")
    lines = [
        _sse({"event": "message", "answer": "Hel", "conversation_id": "c1"}),
        "",  # blank lines are ignored
        _sse({"event": "message", "answer": "lo ", "message_id": "m1"}),
        _sse({"event": "message", "answer": "world"}),
        "data: [DONE]",
    ]
    monkeypatch.setattr(client._session, "post", lambda *a, **k: _FakeResponse(lines))

    deltas = []
    result = client.chat("hi", stream=True, on_delta=deltas.append)

    assert deltas == ["Hel", "lo ", "world"]
    assert result.answer == "Hello world"
    assert result.conversation_id == "c1"
    assert client.conversation_id == "c1"  # persisted for the next turn


def test_streaming_without_on_delta_still_returns_full(monkeypatch):
    client = DifyClient(api_key="k", base_url="http://x/v1", user_id="u")
    lines = [_sse({"event": "message", "answer": "abc", "conversation_id": "c"})]
    monkeypatch.setattr(client._session, "post", lambda *a, **k: _FakeResponse(lines))
    result = client.chat("hi", stream=True)  # no on_delta
    assert result.answer == "abc"


# --- image attachments ------------------------------------------------------

class _JsonResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=True):
        return iter([])


def _client():
    return DifyClient(api_key="k", base_url="http://x/v1", user_id="u")


def _png(tmp_path, name="shot.png"):
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return p


def test_chat_omits_files_when_unused(monkeypatch):
    client = _client()
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(kwargs)
        return _FakeResponse([_sse({"event": "message", "answer": "ok"})])

    monkeypatch.setattr(client._session, "post", fake_post)
    client.chat("hi", stream=True)
    assert "files" not in seen["json"]  # request shape unchanged for text-only


def test_chat_includes_files_when_given(monkeypatch):
    client = _client()
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(kwargs)
        return _FakeResponse([_sse({"event": "message", "answer": "ok"})])

    monkeypatch.setattr(client._session, "post", fake_post)
    descriptor = image_file("f-1")
    client.chat("hi", stream=True, files=[descriptor])
    assert seen["json"]["files"] == [descriptor]


def test_image_file_descriptor():
    assert image_file("abc") == {
        "type": "image",
        "transfer_method": "local_file",
        "upload_file_id": "abc",
    }


def test_upload_file_posts_multipart_and_returns_id(monkeypatch, tmp_path):
    client = _client()
    png = _png(tmp_path)
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return _JsonResponse({"id": "file-abc"})

    monkeypatch.setattr(client._session, "post", fake_post)
    assert client.upload_file(png) == "file-abc"
    assert seen["url"] == "http://x/v1/files/upload"
    assert seen["data"] == {"user": "u"}
    assert seen["files"]["file"][0] == "shot.png"
    assert seen["files"]["file"][2] == "image/png"
    # multipart must not carry the JSON content-type (requests sets the boundary)
    assert "Content-Type" not in seen["headers"]
    assert seen["headers"]["Authorization"] == "Bearer k"


def test_upload_file_rejects_non_image(tmp_path):
    client = _client()
    bad = tmp_path / "notes.txt"
    bad.write_text("hi")
    with pytest.raises(DifyError) as exc:
        client.upload_file(bad)
    assert "Unsupported image type" in str(exc.value)


def test_upload_file_rejects_missing(tmp_path):
    with pytest.raises(DifyError):
        _client().upload_file(tmp_path / "nope.png")


def test_upload_file_rejects_oversized(monkeypatch, tmp_path):
    client = _client()
    png = _png(tmp_path)
    monkeypatch.setattr(dify_client, "MAX_IMAGE_BYTES", 4)
    with pytest.raises(DifyError) as exc:
        client.upload_file(png)
    assert "limit is" in str(exc.value)


def test_image_upload_enabled_legacy_shape(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client._session, "get",
        lambda *a, **k: _JsonResponse({"file_upload": {"image": {"enabled": True}}}),
    )
    assert client.image_upload_enabled() is True


def test_image_upload_disabled_is_detected(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client._session, "get",
        lambda *a, **k: _JsonResponse({"file_upload": {"image": {"enabled": False}}}),
    )
    assert client.image_upload_enabled() is False


def test_image_upload_enabled_new_shape(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client._session, "get",
        lambda *a, **k: _JsonResponse(
            {"file_upload": {"enabled": True, "allowed_file_types": ["image"]}}
        ),
    )
    assert client.image_upload_enabled() is True


def test_image_upload_unknown_when_app_is_silent(monkeypatch):
    client = _client()
    monkeypatch.setattr(client._session, "get", lambda *a, **k: _JsonResponse({}))
    assert client.image_upload_enabled() is None  # unknown -> caller must not warn


def test_app_parameters_survives_network_error(monkeypatch):
    client = _client()

    def boom(*a, **k):
        raise dify_client.requests.RequestException("down")

    monkeypatch.setattr(client._session, "get", boom)
    assert client.app_parameters() == {}
    assert client.image_upload_enabled() is None


def test_upload_file_error_hints_at_vision(monkeypatch, tmp_path):
    client = _client()
    png = _png(tmp_path)
    monkeypatch.setattr(
        client._session,
        "post",
        lambda *a, **k: _JsonResponse({"message": "bad request"}, status_code=400),
    )
    with pytest.raises(DifyError) as exc:
        client.upload_file(png)
    assert "Vision" in str(exc.value)
