from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass
from typing import Optional, List, Literal

from openai import OpenAI


# Logging
logger = logging.getLogger(__name__)

# Gedeelde client (hergebruik tussen requests)
_client: Optional[OpenAI] = None


@dataclass
class SourceSnippet:
    """
    Klein datapakketje voor bronfragmenten.

    - label: korte beschrijving van de bron
      (bijv. "Official website", "Wikipedia (en)", "RCDB").
    - text: opgeschoonde tekst uit die bron.
    - url: optionele URL van de bron (handig voor context in de prompt).
    """
    label: str
    text: str
    url: Optional[str] = None


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
        logger.warning("OPENAI_API_KEY ontbreekt; AI functionaliteit uitgeschakeld.")
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


def summarize_entity_from_sources(
    name: str,
    entity_type: Literal["manufacturer", "park", "coaster", "company"] = "company",
    sources: List[SourceSnippet] | None = None,
    language: str = "en",
    max_chars: int = 800,
) -> Optional[str]:
    """
    Maak een korte beschrijving op basis van meerdere bronfragmenten.

    - Voor parks: extra focus op coaster-line-up en rol in de pretparkwereld.
    - Voor manufacturers: focus op producten/rittypes en belangrijke projecten.
    - Output: 4–6 zinnen, bij voorkeur elk op een aparte regel (line break).
    """
    client = _get_client()
    if not sources or all(not s.text.strip() for s in sources):
        if client is None:
            return None
        return None

    if client is None:
        first = next((s for s in sources if s.text.strip()), None)
        if not first:
            return None
        trimmed = first.text.strip()
        if len(trimmed) > max_chars:
            trimmed = trimmed[:max_chars].rstrip()
        return trimmed

    TOTAL_INPUT_LIMIT = 6000  # characters over alle bronnen
    collected_parts: list[str] = []
    used_chars = 0

    for s in sources:
        text = (s.text or "").strip()
        if not text:
            continue

        header = f"[SOURCE: {s.label}"
        if s.url:
            header += f" — {s.url}"
        header += "]"

        header_with_newline = header + "\n"
        header_len = len(header_with_newline)

        if used_chars + header_len >= TOTAL_INPUT_LIMIT:
            break

        collected_parts.append(header_with_newline)
        used_chars += header_len

        remaining = TOTAL_INPUT_LIMIT - used_chars
        if len(text) > remaining:
            text = text[:remaining].rstrip()

        collected_parts.append(text + "\n\n")
        used_chars += len(text) + 2

        if used_chars >= TOTAL_INPUT_LIMIT:
            break

    if not collected_parts:
        return None

    context = "".join(collected_parts)
    lang_label = _language_label(language)

    system_content = (
        "You are an assistant that writes clear, neutral descriptions for a database "
        "of roller coaster manufacturers, parks, coasters and related companies.\n\n"
        "You receive text fragments from multiple sources (such as official websites, "
        "Wikipedia or RCDB). Your task is to combine these into a concise, factual "
        "summary.\n\n"
        "General style and tone:\n"
        "- Write in a neutral, factual and accessible style.\n"
        "- Avoid marketing language and subjective wording.\n"
        "- Use active sentences and a logical structure.\n"
        "- IMPORTANT: Output 4–6 sentences of plain prose. "
        "Preferably put each sentence on its own line (separated by line breaks).\n"
        "- Do NOT use headings, bullet points or markdown formatting.\n\n"
        "Entity-type specific focus:\n"
        "- If the entity type is 'park':\n"
        "  * briefly describe what kind of park it is and where it is located,\n"
        "  * mention its general history in at most one sentence (for example opening year),\n"
        "  * focus strongly on its roller coasters: types of coasters and 3–8 notable coaster names,\n"
        "  * describe why this park is relevant within the roller coaster / theme park world.\n"
        "- If the entity type is 'manufacturer':\n"
        "  * describe what types of rides/coasters it produces,\n"
        "  * mention important projects or signature coasters if present,\n"
        "  * briefly mention founding year and country if clearly available.\n"
        "- If the entity type is 'coaster':\n"
        "  * focus on coaster type, manufacturer, park, layout style and ride experience.\n\n"
        "Structured details (only if clearly present in the input text):\n"
        "- If the founding year is mentioned (for example 'founded in 1920' or 'opened in 1952'), "
        "include it in the description.\n"
        "- If the country of origin/headquarters or park location is mentioned, include it.\n"
        "- Only include details (founding year, country, ride types, notable coasters) "
        "if they can be clearly inferred from the sources. Do NOT invent information.\n"
    )

    user_content = (
        f"Entity name: {name}\n"
        f"Entity type: {entity_type}\n"
        f"Output language: {lang_label}\n\n"
        "Combine and summarize the following source fragments in 4–6 sentences. "
        "Follow the rules from the system instructions, with extra focus depending on the entity type. "
        "If the entity type is 'park', make sure that at least half of the sentences say something "
        "meaningful about its roller coasters (types, quantity, notable coaster names, and its role in the coaster world). "
        "Use line breaks between sentences if possible. "
        "Do not mention these instructions in your answer, and do not use headings or bullet lists.\n\n"
        f"{context}"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.15,
            max_tokens=400,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
        )

        summary = response.choices[0].message.content or ""
        summary = summary.strip()
        if not summary:
            return None

        if len(summary) > max_chars:
            summary = summary[:max_chars].rstrip()

        return summary

    except Exception as e:
        logger.error("[AI] Error while summarizing entity from sources: %s", e)
        return None


def summarize_company_text(
    text: str,
    language: str = "en",
    max_chars: int = 800,
) -> Optional[str]:
    """
    Backwards-compatible helper voor bestaande code.

    Dit is de oude single-source variant, nu gebouwd bovenop
    summarize_entity_from_sources().

    - text: ruwe/geschoonde tekst van één bron (meestal de officiële website).
    - language: output-taal.
    - max_chars: harde limiet op lengte van de output.
    """
    if not text or not text.strip():
        return None

    snippet = SourceSnippet(
        label="Official website",
        text=text.strip(),
        url=None,
    )

    # We kennen hier de naam en het exacte type niet; dat doen we
    # later in de multi-source extractors. Voor nu gebruiken we de
    # generieke 'company'.
    return summarize_entity_from_sources(
        name="Company",
        entity_type="company",
        sources=[snippet],
        language=language,
        max_chars=max_chars,
    )

def _extract_json_from_response_content(content: str) -> Optional[dict]:
    """
    Probeert JSON te parsen uit het AI-antwoord.
    Ondersteunt zowel 'pure JSON' als JSON binnen ```json ... ``` blokken.
    """
    if not content:
        return None

    text = content.strip()

    # Als er codeblokken zijn, probeer de eerste ```...``` als JSON te nemen
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # strip eventueel 'json' of 'JSON' prefix
            if part.lower().startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except Exception:
                continue

    # Laatste poging: ga ervan uit dat het platte tekst-antwoord zelf JSON is
    try:
        return json.loads(text)
    except Exception:
        logger.warning("Kon JSON niet parsen uit AI-antwoord.")
        return None


def extract_park_facts_from_text(
    text: str,
    language: str = "en",
    max_chars: int = 12000,
) -> Optional[dict]:
    """
    Extraheert gestructureerde basisinformatie over een park uit ruwe tekst
    (typisch de content van de officiële website).

    Output (bij succes) is een dict zoals:
    {
      "name": "Efteling",
      "location_country": "Netherlands",
      "location_city": "Kaatsheuvel",
      "opening_year": 1952,
      "keywords": ["theme park", "family park", "fairy tale forest", ...],
      "mentioned_coasters": ["Python", "Baron 1898", ...]
    }
    """
    client = _get_client()
    if client is None:
        return None

    if not text or not text.strip():
        return None

    trimmed = text.strip()
    if len(trimmed) > max_chars:
        trimmed = trimmed[:max_chars]

    lang_label = _language_label(language)

    system_content = (
        "You are an assistant that extracts factual information about theme parks "
        "and roller coasters from raw website text.\n\n"
        "Your goal is to return a compact JSON object with the most important facts "
        "for further processing in a database.\n\n"
        "Very important:\n"
        "- Only include information that can be reasonably inferred from the input text.\n"
        "- Do NOT invent coaster names, locations or years that are not clearly supported.\n"
        "- If something is unclear or missing, use null or an empty list.\n"
    )

    user_content = (
        f"Input language: {lang_label} (do not translate the text, just analyse it).\n\n"
        "Analyse the following text about a theme park and return ONLY a JSON object "
        "with this structure:\n\n"
        "{\n"
        '  "name": string | null,\n'
        '  "location_country": string | null,\n'
        '  "location_city": string | null,\n'
        '  "opening_year": number | null,\n'
        '  "keywords": string[] (max 20, individual words or short phrases),\n'
        '  "mentioned_coasters": string[] (max 30, coaster names mentioned in the text)\n'
        "}\n\n"
        "Rules:\n"
        "- Use null when you are not sure about a field.\n"
        "- keywords should describe the park, its themes and its main types of attractions.\n"
        "- mentioned_coasters should list only roller coaster names that appear in the text.\n"
        "- Do NOT wrap the JSON in explanations or markdown, just return the JSON.\n\n"
        "Here is the text:\n"
        "--------------------\n"
        f"{trimmed}\n"
        "--------------------\n"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.1,
            max_tokens=400,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
        )
    except Exception as e:
        logger.error("[AI] Error while extracting park facts: %s", e)
        return None

    content = response.choices[0].message.content or ""
    data = _extract_json_from_response_content(content)
    if not isinstance(data, dict):
        return None

    # Basis-normalisatie: zorg dat keys bestaan
    data.setdefault("name", None)
    data.setdefault("location_country", None)
    data.setdefault("location_city", None)
    data.setdefault("opening_year", None)
    data.setdefault("keywords", [])
    data.setdefault("mentioned_coasters", [])

    # Type-correcties
    if not isinstance(data["keywords"], list):
        data["keywords"] = []
    if not isinstance(data["mentioned_coasters"], list):
        data["mentioned_coasters"] = []

    return data

def extract_park_structured_from_sources(
    name: str,
    sources: List[SourceSnippet],
    language: str = "en",
    max_chars: int = 6000,
) -> Optional[dict]:
    """
    Extraheert gestructureerde kerngegevens over een park op basis van meerdere bronnen
    (officiële site, Wikipedia, RCDB, facts-snippet).

    Verwachte output:
    {
      "name": string | null,
      "country_code": string | null,  # 2-letter ISO code, bijv. "NL"
      "opening_year": number | null,
      "opening_month": number | null,
      "opening_day": number | null,
      "latitude": number | null,      # decimal degrees
      "longitude": number | null,     # decimal degrees
      "website_url": string | null
    }
    """
    client = _get_client()
    if client is None:
        return None

    if not sources or all(not (s.text or "").strip() for s in sources):
        return None

    # Context opbouwen uit bronnen (vergelijkbaar met summarize_entity_from_sources)
    used_chars = 0
    parts: list[str] = []

    for s in sources:
        text = (s.text or "").strip()
        if not text:
            continue

        header = f"[SOURCE: {s.label}"
        if s.url:
            header += f" — {s.url}"
        header += "]\n"

        need = len(header) + len(text) + 2
        if used_chars + need > max_chars:
            remaining = max_chars - used_chars - len(header) - 2
            if remaining <= 0:
                break
            text = text[:remaining].rstrip()

        parts.append(header)
        parts.append(text + "\n\n")
        used_chars += len(header) + len(text) + 2

        if used_chars >= max_chars:
            break

    if not parts:
        return None

    context = "".join(parts)
    lang_label = _language_label(language)

    system_content = (
        "You are an assistant that extracts factual, structured information about "
        "theme parks and amusement parks from multiple text fragments. "
        "These fragments can come from an official website, Wikipedia, RCDB, or other sources, "
        "and they may be written in different languages (for example English, Dutch or German).\n\n"
        "Your task is to return a single JSON object with the most important factual fields.\n\n"
        "Very important:\n"
        "- Only include information that can be reasonably inferred from the input text.\n"
        "- If a field is unclear or not present, set it to null.\n"
        "- Do not invent opening dates, locations, coordinates or websites that are not supported by the sources.\n"
        "- You may convert a country name (e.g. 'Netherlands') to a 2-letter ISO country code (e.g. 'NL').\n"
        "- For latitude/longitude, only provide values if coordinates or exact location details are clearly present; "
        "otherwise use null.\n"
        "- Pay special attention to sentences that explicitly mention when the park opened "
        "(for example 'opened on 31 May 1952', or similar phrases in other languages such as Dutch).\n"
    )

    user_content = (
        f"Entity name: {name}\n"
        f"Output language: {lang_label}\n\n"
        "Based on the following source fragments, return ONLY a JSON object with this structure:\n\n"
        "{\n"
        '  "name": string | null,\n'
        '  "country_code": string | null,\n'
        '  "opening_year": number | null,\n'
        '  "opening_month": number | null,\n'
        '  "opening_day": number | null,\n'
        '  "latitude": number | null,\n'
        '  "longitude": number | null,\n'
        '  "website_url": string | null\n'
        "}\n\n"
        "Rules:\n"
        "- Use null when you are not sure about a field.\n"
        "- Only use country_code values that you can confidently map from the text.\n"
        "- If multiple slightly different dates appear, choose the one that clearly corresponds to the park opening.\n"
        "- Opening date can be written in different languages (for example 'opende op 31 mei 1952'). "
        "Always convert it to numeric year/month/day when possible.\n"
        "- Do NOT add comments, explanations or markdown. Return the JSON only.\n\n"
        "Here are the source fragments:\n"
        "--------------------\n"
        f"{context}\n"
        "--------------------\n"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.1,
            max_tokens=400,
            # response_format laten we staan; maar we gaan áltijd via de robuuste JSON-parser
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
        )
    except Exception as e:
        logger.error("[AI] Error while extracting structured park data: %s", e)
        return None

    content = response.choices[0].message.content or ""
    data = _extract_json_from_response_content(content)
    if not isinstance(data, dict):
        logger.error(
            "[AI] Could not parse JSON for structured park data | content=%r",
            content,
        )
        return None

    # Defaults zetten
    data.setdefault("name", None)
    data.setdefault("country_code", None)
    data.setdefault("opening_year", None)
    data.setdefault("opening_month", None)
    data.setdefault("opening_day", None)
    data.setdefault("latitude", None)
    data.setdefault("longitude", None)
    data.setdefault("website_url", None)

    return data


def extract_manufacturer_facts_from_text(
    text: str,
    language: str = "en",
    max_chars: int = 12000,
) -> Optional[dict]:
    """
    Extraheert gestructureerde basisinformatie over een fabrikant/bedrijf uit ruwe tekst
    (typisch de content van de officiële website van een manufacturer).

    Output (bij succes) is een dict zoals:
    {
      "name": "Intamin",
      "location_country": "Switzerland",
      "opening_year": 1967,
      "keywords": [...],
      "ride_types": [...],
      "notable_coasters": [...],
      "notable_parks": [...]
    }
    """
    client = _get_client()
    if client is None:
        return None

    if not text or not text.strip():
        return None

    trimmed = text.strip()
    if len(trimmed) > max_chars:
        trimmed = trimmed[:max_chars]

    lang_label = _language_label(language)

    system_content = (
        "You are an assistant that extracts factual information about roller coaster "
        "and ride manufacturers from raw website text.\n\n"
        "Your goal is to return a compact JSON object with the most important facts "
        "for further processing in a database.\n\n"
        "Very important:\n"
        "- Only include information that can be reasonably inferred from the input text.\n"
        "- Do NOT invent ride types, coaster names, locations or years that are not clearly supported.\n"
        "- If something is unclear or missing, use null or an empty list.\n"
    )

    user_content = (
        f"Input language: {lang_label} (do not translate the text, just analyse it).\n\n"
        "Analyse the following text about a ride/roller coaster manufacturer and "
        "return ONLY a JSON object with this structure:\n\n"
        "{\n"
        '  "name": string | null,\n'
        '  "location_country": string | null,\n'
        '  "opening_year": number | null,\n'
        '  "keywords": string[] (max 20, individual words or short phrases),\n'
        '  "ride_types": string[] (max 20, e.g. "launch coasters", "hyper coasters", "dark rides"),\n'
        '  "notable_coasters": string[] (max 30, coaster names clearly mentioned in the text),\n'
        '  "notable_parks": string[] (max 30, park names clearly mentioned in the text)\n'
        "}\n\n"
        "Rules:\n"
        "- Use null when you are not sure about a field.\n"
        "- keywords should describe the company, its markets and product focus.\n"
        "- ride_types should describe the ride or coaster families the company is known for.\n"
        "- notable_coasters and notable_parks should list only names that appear in the text.\n"
        "- Do NOT wrap the JSON in explanations or markdown, just return the JSON.\n\n"
        "Here is the text:\n"
        "--------------------\n"
        f"{trimmed}\n"
        "--------------------\n"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.1,
            max_tokens=450,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
        )
    except Exception as e:
        logger.error("[AI] Error while extracting manufacturer facts: %s", e)
        return None

    content = response.choices[0].message.content or ""
    data = _extract_json_from_response_content(content)
    if not isinstance(data, dict):
        return None

    # Basisstructuur en defaults
    data.setdefault("name", None)
    data.setdefault("location_country", None)
    data.setdefault("opening_year", None)
    data.setdefault("keywords", [])
    data.setdefault("ride_types", [])
    data.setdefault("notable_coasters", [])
    data.setdefault("notable_parks", [])

    # Type-correcties
    for key in ["keywords", "ride_types", "notable_coasters", "notable_parks"]:
        if not isinstance(data.get(key), list):
            data[key] = []

    return data
