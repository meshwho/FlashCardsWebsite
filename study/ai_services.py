import json
from typing import Type, TypeVar

from django.conf import settings
from google import genai
from google.genai import types
from pydantic import BaseModel

from .ai_schemas import SentenceCheckResult, WordUsageResult


class AIServiceError(Exception):
    pass


StructuredResult = TypeVar(
    "StructuredResult",
    bound=BaseModel,
)


def _get_gemini_client():
    api_key = getattr(settings, "GEMINI_API_KEY", "")

    if not api_key:
        raise AIServiceError(
            "GEMINI_API_KEY is not configured."
        )

    return genai.Client(api_key=api_key)


def _generate_structured_content(
    prompt: str,
    response_schema: Type[StructuredResult],
) -> StructuredResult:
    if not getattr(settings, "AI_FEATURES_ENABLED", False):
        raise AIServiceError(
            "AI features are disabled."
        )

    client = _get_gemini_client()

    try:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )
    except Exception as exc:
        raise AIServiceError(
            f"Gemini request failed: {exc}"
        ) from exc

    response_text = (
        getattr(response, "text", "") or ""
    ).strip()

    if not response_text:
        raise AIServiceError(
            "Gemini returned an empty response."
        )

    try:
        return response_schema.model_validate_json(
            response_text
        )
    except Exception:
        try:
            data = json.loads(response_text)
            return response_schema.model_validate(data)
        except Exception as exc:
            raise AIServiceError(
                "Could not parse Gemini response: "
                f"{exc}. Raw response: "
                f"{response_text[:500]}"
            ) from exc


def check_sentences_with_gemini(
    prompt: str,
) -> SentenceCheckResult:
    return _generate_structured_content(
        prompt,
        SentenceCheckResult,
    )


def explain_word_usage_with_gemini(
    prompt: str,
) -> WordUsageResult:
    return _generate_structured_content(
        prompt,
        WordUsageResult,
    )