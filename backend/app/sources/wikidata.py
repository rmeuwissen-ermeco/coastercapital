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

# Eenvoudige mapping van Wikidata country-entity naar ISO2
COUNTRY_MAP = {
    "Q55": "NL",   # Netherlands
    "Q183": "DE",  # Germany
    "Q142": "FR",  # France
    "Q30": "US",   # United States
    "Q39": "CH",   # Switzerland
    "Q145": "GB",  # United Kingdom
    "Q38": "IT",   # Italy
    "Q29": "ES",   # Spain
    "Q31": "BE",   # Belgium
    "Q36": "PL",   # Poland
    "Q16": "CA",   # Canada
    "Q148": "CN",  # China
    "Q17": "JP",   # Japan
}


def _normalize_query(name: str) -> str:
    """
    Klein beetje opschonen van de zoekterm:
    - stukken vóór ' - ' wegstrippen (bijv. 'Wereld vol Wonderen - Efteling' -> 'Efteling')
    """
    if " - " in name:
        return name.split(" - ")[-1].strip()
    return name.strip()


def find_wikidata_for_name(name: str) -> Optional[Dict[str, Any]]:
    """
    Vind de beste Wikidata entity voor een naam via de zoek-API + haal de entity-data op.
    Dit is generiek genoeg voor zowel parks als manufacturers.
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
        r = requests.get(
            WIKIDATA_SEARCH_URL,
            headers=HEADERS,
            params=search_params,
            timeout=10,
        )
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

    # We bewaren het entity_id erbij voor logging/snippets indien nodig
    entity["_coastercapital_id"] = entity_id
    return entity


def _extract_en_label(entity: dict) -> Optional[str]:
    labels = entity.get("labels", {})
    if "en" in labels:
        return labels["en"].get("value")
    # fallback: pak willekeurige label
    for _, v in labels.items():
        val = v.get("value")
        if val:
            return val
    return None


def _extract_country_code_from_claims(props: dict) -> Optional[str]:
    """
    Probeert country_code te halen uit P17 (country).
    """
    if "P17" not in props:
        return None
    try:
        country_entity = props["P17"][0]["mainsnak"]["datavalue"]["value"]["id"]
        return COUNTRY_MAP.get(country_entity)
    except Exception:
        return None


def _extract_opening_date_from_claims(props: dict, property_ids: list[str]) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """
    Haal een datum uit de claims, bijv.:
    - P1619 (opening date voor parken)
    - P571 (inception voor bedrijven)
    We nemen de eerste property_id die voorkomt.
    """
    for pid in property_ids:
        if pid not in props:
            continue
        try:
            date_str = props[pid][0]["mainsnak"]["datavalue"]["value"]["time"]  # '+1952-05-31T00:00:00Z'
            parts = date_str.replace("+", "").split("T")[0].split("-")
            year = int(parts[0])
            month = int(parts[1])
            day = int(parts[2])
            return year, month, day
        except Exception:
            continue
    return None, None, None


def _extract_coords_from_claims(props: dict) -> tuple[Optional[float], Optional[float]]:
    if "P625" not in props:
        return None, None
    try:
        coords = props["P625"][0]["mainsnak"]["datavalue"]["value"]
        return coords.get("latitude"), coords.get("longitude")
    except Exception:
        return None, None


def _extract_website_from_claims(props: dict) -> Optional[str]:
    if "P856" not in props:
        return None
    try:
        url = props["P856"][0]["mainsnak"]["datavalue"]["value"]
        return url
    except Exception:
        return None


def parse_wikidata_park_entity(entity: dict) -> dict:
    """
    Converteert een Wikidata entity naar ons eigen structured format voor een park:
    name, country_code, opening_year/month/day, latitude, longitude, website_url
    """
    if not entity:
        return {}

    props = entity.get("claims", {})

    result = {
        "name": _extract_en_label(entity),
        "country_code": _extract_country_code_from_claims(props),
        "opening_year": None,
        "opening_month": None,
        "opening_day": None,
        "latitude": None,
        "longitude": None,
        "website_url": _extract_website_from_claims(props),
    }

    # Voor parken gebruiken we P1619 (opening date)
    y, m, d = _extract_opening_date_from_claims(props, ["P1619"])
    result["opening_year"] = y
    result["opening_month"] = m
    result["opening_day"] = d

    lat, lon = _extract_coords_from_claims(props)
    result["latitude"] = lat
    result["longitude"] = lon

    return result


def parse_wikidata_manufacturer_entity(entity: dict) -> dict:
    """
    Converteert een Wikidata entity naar een structured format voor manufacturers:
    name, country_code, opening_year/month/day, website_url

    Coördinaten zijn hier minder belangrijk, dus die laten we weg.
    """
    if not entity:
        return {}

    props = entity.get("claims", {})

    result = {
        "name": _extract_en_label(entity),
        "country_code": _extract_country_code_from_claims(props),
        "opening_year": None,
        "opening_month": None,
        "opening_day": None,
        "website_url": _extract_website_from_claims(props),
    }

    # Voor bedrijven is P571 (inception) meestal het oprichtingsjaar
    # Als fallback zouden we nog P1619 kunnen proberen, maar meestal is P571 genoeg.
    y, m, d = _extract_opening_date_from_claims(props, ["P571", "P1619"])
    result["opening_year"] = y
    result["opening_month"] = m
    result["opening_day"] = d

    return result
