"""End-to-end check of /ws/call with a fake speech-to-text engine (no network, no keys)."""
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.models import TextSignal, TranscriptSegment
from app.stt import SpeechToTextClient, STTError

CHUNK = b"\x00\x00" * 1600  # 100 ms of silence


class FakeSTT(SpeechToTextClient):
    """Says one interim and one final segment per chunk; flushes a closing segment on close()."""

    def __init__(self, fail_on_connect=False):
        super().__init__()
        self.fail_on_connect = fail_on_connect
        self.chunks = 0
        self.closed = False

    async def connect(self):
        if self.fail_on_connect:
            raise STTError("Deepgram rejected the API key.")

    async def send_audio(self, chunk):
        self.chunks += 1
        t = self.chunks * 0.1
        await self._emit_transcript(TranscriptSegment("hel", False, t - 0.1, t, 0.5))
        await self._emit_transcript(TranscriptSegment(f"hello {self.chunks}", True, t - 0.1, t, 0.9))

    async def close(self):
        if not self.closed:
            self.closed = True
            await self._emit_transcript(TranscriptSegment("goodbye", True, 9.0, 9.5, 0.9))


def make_client(stt):
    settings = Settings.from_env({"DEEPGRAM_API_KEY": "test"})
    return TestClient(create_app(settings, stt_factory=lambda _settings: stt))


def test_health():
    response = make_client(FakeSTT()).get("/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "live"


def test_frontend_is_served():
    response = make_client(FakeSTT()).get("/")
    assert response.status_code == 200
    assert "ScamShield Live" in response.text


def test_audio_in_transcript_out_then_flush_on_stop():
    stt = FakeSTT()
    with make_client(stt).websocket_connect("/ws/call") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(CHUNK)
        interim = ws.receive_json()
        final = ws.receive_json()
        assert interim == {"type": "transcript", "text": "hel", "is_final": False,
                           "start": 0.0, "end": 0.1, "confidence": 0.5}
        assert final["text"] == "hello 1" and final["is_final"] is True

        ws.send_json({"type": "stop"})
        assert ws.receive_json()["text"] == "goodbye"  # text flushed during close
        assert ws.receive_json()["type"] == "ended"
    assert stt.closed


def test_malformed_audio_is_dropped_not_forwarded():
    stt = FakeSTT()
    with make_client(stt).websocket_connect("/ws/call") as ws:
        ws.receive_json()  # ready
        ws.send_bytes(b"\x00\x00\x00")  # odd length cannot be 16-bit PCM
        ws.send_json({"type": "stop"})
        assert ws.receive_json()["text"] == "goodbye"
        assert ws.receive_json()["type"] == "ended"
    assert stt.chunks == 0


def test_stt_connect_failure_becomes_a_friendly_error():
    with make_client(FakeSTT(fail_on_connect=True)).websocket_connect("/ws/call") as ws:
        message = ws.receive_json()
    assert message["type"] == "error"
    assert message["code"] == "stt_unavailable"
    assert "API key" in message["message"]


def test_demo_mode_explains_it_is_not_built_yet():
    settings = Settings.from_env({"DEMO_MODE": "true"})
    with TestClient(create_app(settings)).websocket_connect("/ws/call") as ws:
        message = ws.receive_json()
    assert message["type"] == "error"
    assert "Phase 2" in message["message"]


class ScamSTT(FakeSTT):
    """Hears one long scam sentence on the first chunk."""

    async def send_audio(self, chunk):
        self.chunks += 1
        if self.chunks == 1:
            text = "Hi Nana it's me, I need bail money today, please don't tell Mum."
            await self._emit_transcript(TranscriptSegment(text, True, 0.0, 3.0, 0.9))

    async def close(self):
        self.closed = True


class RedAnalyzer:
    async def analyze(self, text):
        return TextSignal(risk=90, scam_type="grandchild", reason="Money and secrecy.", next_action="Hang up.")


def test_speech_leads_to_a_risk_state_in_the_browser():
    settings = Settings.from_env({"DEEPGRAM_API_KEY": "test"})
    app = create_app(settings, stt_factory=lambda _s: ScamSTT(), analyzer_factory=lambda _s: RedAnalyzer())
    with TestClient(app).websocket_connect("/ws/call") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["analysis"] is True
        ws.send_bytes(CHUNK)
        assert ws.receive_json()["type"] == "transcript"
        state = ws.receive_json()
        assert state["type"] == "state"
        assert state["level"] == "red"
        assert state["reason"] == "Money and secrecy."
        ws.send_json({"type": "stop"})
        assert ws.receive_json()["type"] == "ended"


def test_without_a_groq_key_the_browser_is_told_analysis_is_off():
    with make_client(FakeSTT()).websocket_connect("/ws/call") as ws:
        assert ws.receive_json()["analysis"] is False
