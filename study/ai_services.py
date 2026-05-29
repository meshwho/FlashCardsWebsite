import json

from django.conf import settings
from google import genai
from google.genai import types

from .ai_schemas import SentenceCheckResult


class AIServiceError(Exception):
    pass


def _get_gemini_client():
    api_key = getattr(settings, "GEMINI_API_KEY", "")

    if not api_key:
        raise AIServiceError("GEMINI_API_KEY is not configured.")

    return genai.Client(api_key=api_key)


def check_sentences_with_gemini(prompt: str) -> SentenceCheckResult:
    if not getattr(settings, "AI_FEATURES_ENABLED", False):
        raise AIServiceError("AI features are disabled.")

    client = _get_gemini_client()

    try:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SentenceCheckResult,
            ),
        )
    except Exception as exc:
        raise AIServiceError(f"Gemini request failed: {exc}") from exc

    response_text = (getattr(response, "text", "") or "").strip()

    if not response_text:
        raise AIServiceError("Gemini returned an empty response.")

    try:
        return SentenceCheckResult.model_validate_json(response_text)
    except Exception:
        # Fallback на случай, если SDK уже вернул dict-like JSON,
        # но Pydantic не смог разобрать строку напрямую.
        try:
            data = json.loads(response_text)
            return SentenceCheckResult.model_validate(data)
        except Exception as exc:
            raise AIServiceError(
                f"Could not parse Gemini response: {exc}. Raw response: {response_text[:500]}"
            ) from exc