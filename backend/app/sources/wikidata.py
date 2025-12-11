from __future__ import annotations
import logging
from typing import Optional, Dict, Any
import requests

logger = logging.getLogger(__name__)

WIKIDATA_SEARCH_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"

HEADERS = {
    "User-Agent": "CoasterCapital/0.1 (contact: dev@coastercapital.local)",
    "Accept": "application/json",
}


def _normalize_query(name: str) -> str:
    if " - " in name:
        return name.split(" - ")[-1].strip()
    return name.strip()


def find_wikidata_for_name(name: str) -> Optional[Dict[str, Any]]:
    """
    Vind de beste Wikidata entity voor een parknaam via de zoek-API + haal de entity-data op.
    """
    query = _normalize_query(name)

    search_params = {
        "action": "wbsearchentities",
        "search": query,
        "language": "en",
        "format": "json",
        "limit": 1,
    }

    try:
        r = requests.get(WIKIDATA_SEARCH_URL, headers=HEADERS, params=search_params, timeout=10)
        r.raise_for_status()
    except Exception as e:
        logger.error("[Wikidata] Search request failed for %r: %s", query, e)
        return None

    data = r.json()
    if not data.get("search"):
        logger.info("[Wikidata] No result for query=%r", query)
        return None

    entity_id = data["search"][0]["id"]  # bijv Q183393
    entity_url = WIKIDATA_ENTITY_URL.format(entity_id)

    try:
        r2 = requests.get(entity_url, headers=HEADERS, timeout=10)
        r2.raise_for_status()
    except Exception as e:
        logger.error("[Wikidata] Entity fetch failed for %r: %s", entity_id, e)
        return None

    full = r2.json()
    entities = full.get("entities", {})
    entity = entities.get(entity_id)

    if not entity:
        return None

    return entity


def parse_wikidata_park_entity(entity: dict) -> dict:
    """
    Converteert een Wikidata entity naar ons eigen structured format:
    name, country_code, opening_year/month/day, latitude, longitude
    """
    if not entity:
        return {}

    props = entity.get("claims", {})
    labels = entity.get("labels", {})
    en_label = labels.get("en", {}).get("value")

    result = {
        "name": en_label,
        "country_code": None,
        "opening_year": None,
        "opening_month": None,
        "opening_day": None,
        "latitude": None,
        "longitude": None,
        "website_url": None,
    }

    # P17 = country
    if "P17" in props:
        try:
            country_entity = props["P17"][0]["mainsnak"]["datavalue"]["value"]["id"]
            # kleine mapping
            COUNTRY_MAP = {
                "Q55": "NL",  # Netherlands
                "Q183": "DE",
                "Q142": "FR",
                "Q30": "US",
            }
            result["country_code"] = COUNTRY_MAP.get(country_entity)
        except Exception:
            pass

    # P1619 = opening date
    if "P1619" in props:
        try:
            date_str = props["P1619"][0]["mainsnak"]["datavalue"]["value"]["time"]  # '+1952-05-31T00:00:00Z'
            parts = date_str.replace("+", "").split("T")[0].split("-")
            year = int(parts[0])
            month = int(parts[1])
            day = int(parts[2])
            result["opening_year"] = year
            result["opening_month"] = month
            result["opening_day"] = day
        except Exception:
            pass

    # P625 = coordinate location
    if "P625" in props:
        try:
            coords = props["P625"][0]["mainsnak"]["datavalue"]["value"]
            result["latitude"] = coords.get("latitude")
            result["longitude"] = coords.get("longitude")
        except Exception:
            pass

    # P856 = official website
    if "P856" in props:
        try:
            url = props["P856"][0]["mainsnak"]["datavalue"]["value"]
            result["website_url"] = url
        except Exception:
            pass

    return result
