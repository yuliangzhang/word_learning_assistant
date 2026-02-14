from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from word_assistance.config import AUDIO_DIR

UTC = timezone.utc

VOICE_PRESETS = {
    "en-GB": [
        {"id": "en-GB-SoniaNeural", "label": "English (UK) - Sonia"},
        {"id": "en-GB-RyanNeural", "label": "English (UK) - Ryan"},
        {"id": "en-GB-LibbyNeural", "label": "English (UK) - Libby"},
    ],
    "en-US": [
        {"id": "en-US-JennyNeural", "label": "English (US) - Jenny"},
        {"id": "en-US-GuyNeural", "label": "English (US) - Guy"},
    ],
    "en-AU": [
        {"id": "en-AU-NatashaNeural", "label": "English (AU) - Natasha"},
        {"id": "en-AU-WilliamNeural", "label": "English (AU) - William"},
    ],
}

OPENAI_VOICE_FALLBACK = {
    "en-GB": "alloy",
    "en-US": "alloy",
    "en-AU": "alloy",
}


class SpeechService:
    def __init__(self) -> None:
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.openai_base = os.getenv("WORD_ASSISTANCE_OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.stt_model = os.getenv("WORD_ASSISTANCE_STT_MODEL", "gpt-4o-mini-transcribe")
        self.tts_model = os.getenv("WORD_ASSISTANCE_TTS_MODEL", "gpt-4o-mini-tts")

    def list_voices(self) -> dict:
        return VOICE_PRESETS

    async def synthesize(self, *, text: str, accent: str = "en-GB", voice: str | None = None) -> Path:
        if not text.strip():
            raise ValueError("text is empty")

        accent = accent if accent in VOICE_PRESETS else "en-GB"
        final_voice = voice or VOICE_PRESETS[accent][0]["id"]
        ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        out = AUDIO_DIR / f"tts_{ts}.mp3"

        edge_error = None
        try:
            import edge_tts

            communicator = edge_tts.Communicate(text=text, voice=final_voice)
            await communicator.save(str(out))
            return out
        except Exception as exc:
            edge_error = exc

        if self.openai_api_key:
            self._openai_tts(text=text, accent=accent, out=out)
            return out

        raise RuntimeError(f"TTS unavailable. edge_tts={edge_error}")

    def transcribe(self, audio_path: Path, filename: str = "audio.webm") -> str:
        if not audio_path.exists() or audio_path.stat().st_size == 0:
            raise ValueError("audio file is empty")
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not configured for STT")

        url = self.openai_base.rstrip("/") + "/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.openai_api_key}"}
        with audio_path.open("rb") as f:
            files = {"file": (filename, f, "audio/webm")}
            data = {"model": self.stt_model}
            with httpx.Client(timeout=90) as client:
                resp = client.post(url, headers=headers, data=data, files=files)
                resp.raise_for_status()
                payload = resp.json()
        text = str(payload.get("text") or "").strip()
        if not text:
            raise RuntimeError("STT result empty")
        return text

    def _openai_tts(self, *, text: str, accent: str, out: Path) -> None:
        voice = OPENAI_VOICE_FALLBACK.get(accent, "alloy")
        url = self.openai_base.rstrip("/") + "/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.tts_model,
            "voice": voice,
            "input": text,
            "format": "mp3",
        }
        with httpx.Client(timeout=90) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            out.write_bytes(resp.content)
