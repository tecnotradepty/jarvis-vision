"""Optional conversational Gemini API integration via google-genai."""

from __future__ import annotations

import os


SYSTEM_PROMPT = (
    "Eres Gemini, el asistente de escritorio personal del usuario en Windows. "
    "Responde en español de forma clara, natural y concisa (máximo 2 a 3 frases), "
    "sin markdown ni viñetas porque tu respuesta se leerá en voz alta."
)


class GeminiBrain:
    """Calls Gemini API when an API key is configured; degrades cleanly otherwise."""

    def __init__(self, api_key: str = "", model: str = "gemini-2.5-flash") -> None:
        self.model = model
        self._api_key = self._resolve_key(api_key)
        self._client = None

    @staticmethod
    def _resolve_key(explicit_key: str) -> str:
        return (
            explicit_key.strip()
            or os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()
        )

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def set_api_key(self, api_key: str) -> None:
        self._api_key = self._resolve_key(api_key)
        self._client = None

    def ask(self, prompt: str) -> str:
        if not self._api_key:
            return (
                "No reconozco ese comando local. Agrega tu Gemini API Key en el panel "
                "para responder preguntas con IA."
            )

        try:
            from google import genai
            from google.genai import types

            if self._client is None:
                self._client = genai.Client(api_key=self._api_key)

            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.6,
                    max_output_tokens=220,
                ),
            )
            text = (response.text or "").strip()
            return text or "No recibí respuesta del modelo."
        except Exception as exc:
            return f"Error consultando Gemini API: {exc}"
