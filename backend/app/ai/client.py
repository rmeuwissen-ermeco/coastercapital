from __future__ import annotations

import os
from typing import Optional

from openai import OpenAI

# Gedeelde client (hergebruik tussen requests)
_client: Optional[OpenAI] = None


def _get_client() -> Optional[OpenAI]:
    """
    Haal een gedeelde OpenAI-client op.
    Als er geen OPENAI_API_KEY is gezet, geven we None terug.
    Zo blijft de app gewoon werken zonder AI-key.
    """
    global _client

    if _client is not None:
        return _client

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        # Geen key gezet -> geen AI
        return None

    _client = OpenAI(api_key=api_key)
    return _client


def _language_label(lang_code: str) -> str:
    """
    Zet een korte taalcode om naar een menselijk label
    voor in de prompt.
    """
    mapping = {
        "en": "English",
        "nl": "Dutch",
        "de": "German",
        "fr": "French",
    }
    return mapping.get(lang_code.lower(), "English")


def summarize_company_text(
    text: str,
    language: str = "en",
    max_chars: int = 800,
) -> Optional[str]:
    """
    Maak een korte bedrijfsbeschrijving op basis van ruwe tekst.

    - 'language' bepaalt de output-taal ("en", "nl", ...).
    - Output: 2–4 zinnen, lopende tekst zonder headings of bullet lists.
    - Focus op coaster-relevante info als die in de bron aanwezig is.
    - Bij fouten of ontbrekende API-key -> None (caller valt dan terug op heuristiek).
    """
    client = _get_client()
    if client is None:
        return None

    if not text or not text.strip():
        return None

    trimmed = text.strip()
    # Bescherm tegen extreem lange input
    if len(trimmed) > 4000:
        trimmed = trimmed[:4000]

    lang_label = _language_label(language)

    system_content = (
        "You are an assistant that writes clear, neutral company descriptions "
        "for a database of roller coaster manufacturers, parks and related companies. "
        "Your style must be neutral, factual and easy to read, and suitable for search engines.\n\n"
        "Guidelines:\n"
        "- Write in a neutral, factual and accessible style.\n"
        "- Avoid marketing language and subjective wording.\n"
        "- Use active sentences and a logical structure.\n"
        "- Provide practical, relevant information about what the company does, "
        "its products/services and typical customers.\n"
        "- Do not include long historical overviews or unnecessary details.\n"
        "- Integrate relevant keywords naturally in sentences that clarify the content.\n"
        "- IMPORTANT: Output 2–4 sentences of plain prose. "
        "Do NOT use headings, bullet points or markdown formatting.\n\n"
        "Roller coaster focus:\n"
        "- When the source text clearly mentions roller coasters, briefly describe what types of coasters "
        "the company is known for (e.g. family coasters, launch coasters, wooden coasters).\n"
        "- If notable coasters or signature models are mentioned, you may reference one or two examples.\n"
        "- Only mention coaster-related details if they are clearly present in the input text. "
        "Do not invent ride names or models."
    )

    user_content = (
        f"Write a short company description in {lang_label}. "
        "Summarize the following text in 2–4 sentences. "
        "Focus on what the company does, its main products or services, typical clients or markets, "
        "and—only if clearly present—its role in the roller coaster industry. "
        "Do not mention these instructions in your answer, and do not use headings or bullet lists.\n\n"
        f"{trimmed}"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.3,
            max_tokens=350,
            messages=[
                {
                    "role": "system",
                    "content": system_content,
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
        )

        summary = response.choices[0].message.content or ""
        summary = summary.strip()
        if not summary:
            return None

        if len(summary) > max_chars:
            summary = summary[: max_chars].rstrip()

        return summary

    except Exception as e:
        print(f"[AI] Error while summarizing company text: {e}")
        return None
