"""Gemini 2.5 Flash TTS wrapper with per-agent voice and mood-based style."""

import io
import logging
import struct
import wave
from google import genai
from google.genai import types
from core.config import settings

logger = logging.getLogger(__name__)

# Per-agent voice assignments
AGENT_VOICES: dict[str, str] = {
    "agent_sam": "Charon",
    "agent_maya": "Kore",
    "agent_isabella": "Aoede",
    "agent_klaus": "Enceladus",
    "agent_tom": "Fenrir",
    "agent_mei": "Leda",
    "agent_latoya": "Zephyr",
}

DEFAULT_VOICE = "Puck"

# Mood -> speaking-style prefix
MOOD_STYLE: dict[str, str] = {
    "happy": "Say warmly and cheerfully:",
    "sad": "Say gently and with a somber tone:",
    "angry": "Say with frustration and intensity:",
    "excited": "Say with enthusiasm and energy:",
    "anxious": "Say nervously and with hesitation:",
    "neutral": "Say in a calm, conversational tone:",
}


class VoiceService:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    def _get_voice(self, agent_id: str) -> str:
        return AGENT_VOICES.get(agent_id, DEFAULT_VOICE)

    def _get_style_prompt(self, mood: str) -> str:
        return MOOD_STYLE.get(mood, MOOD_STYLE["neutral"])

    async def synthesize(self, agent_id: str, text: str, mood: str = "neutral") -> bytes:
        """Generate TTS audio bytes for the given text using Gemini 2.5 Flash TTS."""
        voice_name = self._get_voice(agent_id)
        style = self._get_style_prompt(mood)
        prompt = f"{style} {text}"

        logger.info("TTS request: agent=%s voice=%s mood=%s", agent_id, voice_name, mood)

        response = await self.client.aio.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice_name,
                        )
                    )
                ),
            ),
        )

        part = response.candidates[0].content.parts[0]
        raw_pcm = part.inline_data.data
        mime = part.inline_data.mime_type or ""

        # Parse sample rate from mime_type like "audio/L16;rate=24000"
        sample_rate = 24000
        if "rate=" in mime:
            try:
                sample_rate = int(mime.split("rate=")[1].split(";")[0])
            except (ValueError, IndexError):
                pass

        # Wrap raw PCM in a proper WAV header so browsers can play it
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(raw_pcm)

        return buf.getvalue()
