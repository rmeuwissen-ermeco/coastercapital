from __future__ import annotations

from typing import Optional, Dict, Any

import requests

WIKIPEDIA_API_URL = "https://{lang}.wikipedia.org/w/api.php"


def _call_wikipedia_api(params: Dict[str, Any], language: str = "en") -> Optional[Dict[str, Any]]:
    """
    Kleine helper om de Wikipedia API aan te roepen.
    Fouten -> None, we willen nooit het hele extractieproces laten falen.
    """
    try:
        resp = requests.get(
            WIKIPEDIA_API_URL.format(lang=language),
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _find_best_pageid_for_name(name: str, language: str = "en") -> Optional[Dict[str, Any]]:
    """
    Gebruik de zoek-API van Wikipedia om de beste match te vinden.
    We pakken alleen het eerste resultaat en doen een simpele naam-check.
    """
    params = {
        "action": "query",
        "list": "search",
        "srsearch": name,
        "format": "json",
        "srlimit": 1,
    }
    data = _call_wikipedia_api(params, language=language)
    if not data:
        return None

    results = data.get("query", {}).get("search", [])
    if not results:
        return None

    top = results[0]
    title = top.get("title", "")
    if not title:
        return None

    # Simpele sanity-check: titel moet enigszins overeenkomen met de naam
    name_lower = name.lower()
    title_lower = title.lower()
    if name_lower not in title_lower and title_lower not in name_lower:
        # bv. zoekterm "Mack" en resultaat "Mack (surname)" -> beter overslaan
        return None

    return {"pageid": top.get("pageid"), "title": title}


def _get_page_extract(pageid: int, language: str = "en") -> Optional[str]:
    """
    Haal de 'extract' (platte tekst, intro) op voor een Wikipedia-pagina.
    """
    params = {
        "action": "query",
        "pageids": pageid,
        "prop": "extracts",
        "explaintext": 1,
        "exintro": 1,
        "format": "json",
    }
    data = _call_wikipedia_api(params, language=language)
    if not data:
        return None

    pages = data.get("query", {}).get("pages", {})
    page = pages.get(str(pageid))
    if not page:
        return None

    extract = page.get("extract")
    if not extract:
        return None

    text = extract.strip()
    return text or None


def get_wikipedia_summary_for_manufacturer(name: str, language: str = "en") -> Optional[str]:
    """
    Hoog-niveau helper:
    - Zoek een passende Wikipedia-pagina obv 'name'
    - Haal de tekstuele intro op
    - Geef deze terug als basis voor AI-samenvatting

    Bij elke fout -> None.
    """
    match = _find_best_pageid_for_name(name, language=language)
    if not match or not match.get("pageid"):
        return None

    pageid = match["pageid"]
    return _get_page_extract(pageid, language=language)
