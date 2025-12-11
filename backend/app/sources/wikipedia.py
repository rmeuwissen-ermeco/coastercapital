from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
import requests

logger = logging.getLogger(__name__)

WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"

HEADERS = {
    "User-Agent": "CoasterCapital/0.1 (contact: dev@coastercapital.local)",
    "Accept": "application/json",
}


@dataclass
class WikipediaPage:
    lang: str
    title: str
    url: str
    extract: str


def _normalize_query(name: str) -> str:
    if " - " in name:
        return name.split(" - ")[-1].strip()
    return name.strip()


def find_best_wikipedia_page(name: str, lang: str = "en") -> Optional[WikipediaPage]:
    query = _normalize_query(name)

    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": 1,
        "format": "json",
    }

    try:
        resp = requests.get(WIKIPEDIA_API_URL, headers=HEADERS, params=search_params, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.error("[Wikipedia] Search failed for %r: %s", query, e)
        return None

    data = resp.json()
    top = data.get("query", {}).get("search", [])
    if not top:
        return None

    pageid = top[0].get("pageid")
    title = top[0].get("title") or query

    extract_params = {
        "action": "query",
        "prop": "extracts",
        "pageids": pageid,
        "explaintext": 1,
        "exsectionformat": "plain",
        "format": "json",
    }

    try:
        resp2 = requests.get(WIKIPEDIA_API_URL, headers=HEADERS, params=extract_params, timeout=10)
        resp2.raise_for_status()
    except Exception as e:
        logger.error("[Wikipedia] Extract failed for %r: %s", pageid, e)
        return None

    data2 = resp2.json()
    extract = data2.get("query", {}).get("pages", {}).get(str(pageid), {}).get("extract", "")

    url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"

    return WikipediaPage(
        lang=lang,
        title=title,
        url=url,
        extract=extract,
    )
