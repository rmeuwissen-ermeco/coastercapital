# backend/app/sources/rcdb.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


@dataclass
class RcdbPage:
    url: str
    text: str


RCDB_BASE = "https://rcdb.com"


def _get_html(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.warning("RCDB request failed: %s", e)
        return None


def _extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Simpele tekst-extractie; later kun je dit verfijnen.
    for script in soup(["script", "style", "noscript"]):
        script.extract()

    texts = [t.strip() for t in soup.stripped_strings]
    return "\n".join(t for t in texts if t)


def find_rcdb_page_for_name(name: str) -> Optional[RcdbPage]:
    """
    *Let op*: de exacte search-URL van RCDB moet je in de browser even checken.
    Deze implementatie gaat uit van een query-parameter `?q=` op de homepage.

    Suggestie:
    - Open in je browser: https://rcdb.com/?q=efteling
    - Of: https://rcdb.com/search?q=efteling
    en kijk welke werkt; pas de URL hieronder zo nodig aan.
    """

    # >>> HIER eventueel aanpassen na het checken in de browser <<<
    search_url = f"{RCDB_BASE}/?q={quote_plus(name)}"

    html = _get_html(search_url)
    if not html:
        return None

    text = _extract_visible_text(html)
    return RcdbPage(url=search_url, text=text)
