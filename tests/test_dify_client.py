import json

from coding_cli.dify_client import DifyClient


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
