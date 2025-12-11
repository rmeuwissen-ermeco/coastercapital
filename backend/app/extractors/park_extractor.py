from __future__ import annotations

import logging
import re
from typing import Any, List, Optional

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from .. import models
from ..ai.client import (
    SourceSnippet,
    summarize_entity_from_sources,
    extract_park_facts_from_text,
    extract_park_structured_from_sources,
)
from ..routers.utils import create_suggestion_diff
from ..sources.wikidata import find_wikidata_for_name, parse_wikidata_park_entity
from ..sources.wikipedia import find_best_wikipedia_page

logger = logging.getLogger(__name__)


def _split_into_sentences(text: str) -> list[str]:
    """
    Simpele zins-splitter op basis van ., ! en ?.
    Niet perfect, maar goed genoeg voor filtering.
    """
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _select_relevant_sentences(
    text: str,
    keywords: list[str],
    coaster_names: list[str],
    max_sentences: int = 60,
) -> str:
    """
    Selecteert zinnen uit 'text' die één van de keywords of coaster-namen bevatten.
    Als er niets matcht, wordt een fallback gemaakt: de eerste N zinnen.
    """
    if not text:
        return ""

    sentences = _split_into_sentences(text)
    if not sentences:
        return ""

    kw_lower = {k.lower() for k in keywords if isinstance(k, str)}
    coaster_lower = {c.lower() for c in coaster_names if isinstance(c, str)}

    selected: list[str] = []

    for s in sentences:
        s_lower = s.lower()
        if any(k in s_lower for k in kw_lower) or any(
            c in s_lower for c in coaster_lower
        ):
            selected.append(s)
        if len(selected) >= max_sentences:
            break

    if not selected:
        selected = sentences[:max_sentences]

    return " ".join(selected)


class ParkExtractor:
    """
    Extractor voor parks (CoasterCapital):

    Bronnen in volgorde van belangrijkheid:
    1) Wikidata  -> structured (naam, landcode, opening, coords, website)
    2) Wikipedia -> tekstuele context (coasters, geschiedenis, status)
    3) Officiële website -> extra context + keywords/coasternamen (AI-facts)
    4) RCDB     -> UITGESCHAKELD in deze versie
    5) Heuristiek -> pure noodfallback (title/meta)

    De AI wordt gebruikt om:
    - multi-source notes te schrijven (focus op coasters),
    - aanvullende structured data uit tekst te halen *achter* Wikidata.
    """

    def __init__(self, db: Session, park: models.Park):
        self.db = db
        self.park = park

    # ------------------------
    # Basis HTTP/DB helpers
    # ------------------------

    def _fetch_html(self, url: str) -> tuple[str, str]:
        """HTML ophalen, geeft (status_code, raw_html) terug."""
        resp = requests.get(url, timeout=10)
        return str(resp.status_code), resp.text

    def _store_source_page(
        self,
        url: str,
        status_code: str,
        raw_html: str,
        clean_text: str,
    ) -> models.SourcePage:
        """
        Slaat de bronpagina op in SourcePage en geeft het record terug.
        Kan gebruikt worden voor officiële site of Wikipedia.
        """
        source_page = models.SourcePage(
            entity_type="park",
            entity_id=self.park.id,
            url=url,
            status_code=status_code,
            raw_html=raw_html[:10000],
            clean_text=clean_text[:10000],
        )
        self.db.add(source_page)
        self.db.commit()
        self.db.refresh(source_page)
        return source_page

    # ------------------------
    # Heuristieken
    # ------------------------

    def _heuristic_name(self, soup: BeautifulSoup) -> str | None:
        """
        Probeer een betere naam uit <title> te halen.

        Strategie:
        - Als de title 'Slogan - Efteling' is, nemen we het laatste deel.
        - Alleen gebruiken als hij verschilt van de huidige naam.
        """
        title_tag = soup.find("title")
        if not title_tag:
            return None

        title_text = title_tag.get_text().strip()
        if not title_text:
            return None

        candidate = title_text

        # Veel voorkomende pattern: 'Slogan - Parknaam'
        if " - " in candidate:
            parts = [p.strip() for p in candidate.split(" - ") if p.strip()]
            if len(parts) >= 2:
                candidate = parts[-1]

        if candidate == (self.park.name or "").strip():
            return None

        return candidate

    def _heuristic_notes(self, soup: BeautifulSoup) -> str | None:
        """Fallback: meta description als snelle beschrijving."""
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if not meta_desc:
            meta_desc = soup.find("meta", attrs={"property": "og:description"})

        if not meta_desc:
            return None

        text = (meta_desc.get("content") or "").strip()
        if not text:
            return None

        if text == (self.park.notes or ""):
            return None

        return text

    # ------------------------
    # AI-facts uit officiële site
    # ------------------------

    def _extract_keywords_from_official(self, text: str) -> dict:
        """
        AI-call 1: haal kernfeiten, kernwoorden en coasternamen uit de officiële site.
        Als de AI faalt, krijg je een lege dict.
        """
        facts = extract_park_facts_from_text(text, language="en") or {}
        return {
            "name": facts.get("name"),
            "location_country": facts.get("location_country"),
            "location_city": facts.get("location_city"),
            "opening_year": facts.get("opening_year"),
            "keywords": facts.get("keywords") or [],
            "mentioned_coasters": facts.get("mentioned_coasters") or [],
        }

    # ------------------------
    # Source snippets
    # ------------------------

    def _get_official_snippet(
        self,
        clean_text: str,
        url: str,
        max_chars: int = 8000,
    ) -> SourceSnippet:
        """Maak een SourceSnippet voor de officiële website (ruime tekst, maar afgekapt)."""
        text = clean_text.strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip()
        return SourceSnippet(
            label="Official website",
            text=text,
            url=url,
        )

    def _get_wikipedia_snippet(
        self,
        keywords: list[str],
        coaster_names: list[str],
    ) -> Optional[SourceSnippet]:
        """
        Haalt Wikipedia-extract op, filtert zinnen op kernwoorden/coasternamen
        en slaat de bron op als SourcePage.
        """
        page = find_best_wikipedia_page(self.park.name)
        if not page or not page.extract:
            return None

        filtered_text = _select_relevant_sentences(
            page.extract,
            keywords=keywords,
            coaster_names=coaster_names,
            max_sentences=80,
        )

        # Loggen in SourcePage (zodat je later kunt terugzien wat gebruikt is)
        self._store_source_page(
            url=page.url,
            status_code="200",
            raw_html=page.extract,
            clean_text=filtered_text,
        )

        return SourceSnippet(
            label=f"Wikipedia ({page.lang})",
            text=filtered_text,
            url=page.url,
        )

    def _get_wikidata_snippet(
        self,
        wikidata_struct: dict,
    ) -> Optional[SourceSnippet]:
        """
        Maak een tekstuele snippet uit de Wikidata structured info, zodat de
        multi-source AI-samenvatting deze context ook meeneemt.
        """
        if not wikidata_struct:
            return None

        lines: list[str] = []
        name = wikidata_struct.get("name")
        if name:
            lines.append(f"Official name: {name}")

        country = wikidata_struct.get("country_code")
        if country:
            lines.append(f"Country code: {country}")

        oy = wikidata_struct.get("opening_year")
        om = wikidata_struct.get("opening_month")
        od = wikidata_struct.get("opening_day")
        if oy:
            if om and od:
                lines.append(f"Opening date: {oy:04d}-{om:02d}-{od:02d}")
            else:
                lines.append(f"Opening year: {oy}")

        lat = wikidata_struct.get("latitude")
        lon = wikidata_struct.get("longitude")
        if lat is not None and lon is not None:
            lines.append(f"Coordinates: {lat}, {lon}")

        site = wikidata_struct.get("website_url")
        if site:
            lines.append(f"Official website: {site}")

        if not lines:
            return None

        text = "\n".join(lines)
        return SourceSnippet(
            label="Wikidata (structured facts)",
            text=text,
            url=None,
        )

    # ------------------------
    # AI-samenvatting (notes)
    # ------------------------

    def _extract_notes_with_ai(self, snippets: list[SourceSnippet]) -> str | None:
        """
        AI-call 2a: multi-source samenvatting over het park met focus op coasters.
        """
        if not snippets:
            return None

        try:
            ai_summary = summarize_entity_from_sources(
                name=self.park.name,
                entity_type="park",
                sources=snippets,
                language="en",
                max_chars=800,
            )
        except Exception as e:
            logger.error("[ParkExtractor] Error during summarize_entity_from_sources: %s", e)
            return None

        if not ai_summary:
            return None

        return str(ai_summary).strip() or None

    # ------------------------
    # Hoofdstroom
    # ------------------------

    def run(self) -> dict:
        """
        Voert de volledige extractie uit en maakt eventueel een DataSuggestion aan.
        Geeft een klein resultaat-dict terug.
        """

        if not self.park.website_url:
            raise ValueError("Geen website_url bekend voor dit park.")

        url = self.park.website_url

        # 1. HTML ophalen van de officiële site
        status_code, raw_html = self._fetch_html(url)

        # 2. Soup + plain text
        soup = BeautifulSoup(raw_html, "html.parser")
        clean_text = soup.get_text(separator="\n").strip()

        # 3. SourcePage loggen voor de officiële site
        source_page = self._store_source_page(
            url=url,
            status_code=status_code,
            raw_html=raw_html,
            clean_text=clean_text,
        )

        # 4. Huidige data + basis updated_data
        current_data = {
            "name": self.park.name,
            "country_code": self.park.country_code,
            "website_url": self.park.website_url,
            "notes": self.park.notes,
            "opening_year": self.park.opening_year,
            "opening_month": self.park.opening_month,
            "opening_day": self.park.opening_day,
            "latitude": self.park.latitude,
            "longitude": self.park.longitude,
        }
        updated_data = dict(current_data)

        # ------------------------
        # 4a. Wikidata eerst (structured)
        # ------------------------
        wikidata_struct: dict[str, Any] = {}
        entity = find_wikidata_for_name(self.park.name)
        if entity:
            wikidata_struct = parse_wikidata_park_entity(entity) or {}
            logger.info(
                "[ParkExtractor] Wikidata structured for %s: %r",
                self.park.name,
                wikidata_struct,
            )

        # ------------------------
        # 4b. AI-facts uit officiële site (keywords/coasters)
        # ------------------------
        facts = self._extract_keywords_from_official(clean_text)
        keywords = facts.get("keywords", []) or []
        mentioned_coasters = facts.get("mentioned_coasters", []) or []

        # Voeg de parknaam zelf toe als keyword
        if self.park.name:
            keywords.append(self.park.name)

        # Facts-snippet voor AI-samenvatting
        facts_lines: list[str] = []
        if facts.get("name"):
            facts_lines.append(f"Name from official site (AI): {facts['name']}")
        if facts.get("location_city") or facts.get("location_country"):
            city = facts.get("location_city") or ""
            country = facts.get("location_country") or ""
            loc = ", ".join(part for part in [city, country] if part)
            facts_lines.append(f"Location from official site (AI): {loc}")
        if facts.get("opening_year"):
            facts_lines.append(f"Opening year (from official site, AI): {facts['opening_year']}")
        if keywords:
            facts_lines.append("Keywords: " + ", ".join(keywords[:20]))
        if mentioned_coasters:
            facts_lines.append(
                "Notable coasters (from official site, AI): "
                + ", ".join(mentioned_coasters[:20])
            )
        facts_text = "\n".join(facts_lines).strip() if facts_lines else ""

        # ------------------------
        # 4c. Bron-snippets voor multi-source AI
        # ------------------------
        snippets: list[SourceSnippet] = []

        # Officiële website
        official_snippet = self._get_official_snippet(clean_text, url)
        snippets.append(official_snippet)

        # Wikidata snippet (tekstuele representatie van structured facts)
        wikidata_snippet = self._get_wikidata_snippet(wikidata_struct)
        if wikidata_snippet:
            snippets.append(wikidata_snippet)

        # AI facts-snippet uit officiële site
        if facts_text:
            facts_snippet = SourceSnippet(
                label="Extracted facts from official website (AI)",
                text=facts_text,
                url=None,
            )
            snippets.append(facts_snippet)

        # Wikipedia (optioneel, als het lukt)
        wiki_snippet = self._get_wikipedia_snippet(
            keywords=keywords,
            coaster_names=mentioned_coasters,
        )
        if wiki_snippet:
            snippets.append(wiki_snippet)

        # ------------------------
        # 4d. AI-call 2a: samenvatting over alle bronnen (notes)
        # ------------------------
        ai_notes = self._extract_notes_with_ai(snippets)
        if ai_notes:
            updated_data["notes"] = ai_notes
        else:
            heuristic_notes = self._heuristic_notes(soup)
            if heuristic_notes:
                updated_data["notes"] = heuristic_notes

        # ------------------------
        # 4e. AI-call 2b: structured data uit alle tekstbronnen
        #      (achter Wikidata; alleen als Wikidata het niet al invult)
        # ------------------------
        structured_ai: dict[str, Any] = {}
        try:
            tmp = extract_park_structured_from_sources(
                name=self.park.name,
                sources=snippets,
                language="en",
            )
            if isinstance(tmp, dict):
                structured_ai = tmp
        except Exception as e:
            logger.error(
                "[ParkExtractor] Structured extract (AI) failed for %s: %s",
                self.park.name,
                e,
            )
            structured_ai = {}

        logger.info(
            "[ParkExtractor] Structured (AI) data for %s: %r",
            self.park.name,
            structured_ai,
        )

        # ------------------------
        # 4f. Finale veldkeuze (prioriteit: Wikidata > AI-structured > heuristiek)
        # ------------------------

        # NAAM
        name_from_wikidata = wikidata_struct.get("name")
        name_from_ai = structured_ai.get("name")
        name_from_title = self._heuristic_name(soup)

        new_name = None
        if name_from_wikidata:
            new_name = name_from_wikidata
        elif name_from_ai:
            new_name = name_from_ai
        elif name_from_title:
            new_name = name_from_title

        if new_name and new_name != self.park.name:
            updated_data["name"] = new_name

        # LANDCODE
        country_wd = wikidata_struct.get("country_code")
        country_ai = structured_ai.get("country_code")
        country_new = country_wd or country_ai
        if country_new and country_new != self.park.country_code:
            updated_data["country_code"] = country_new

        # OPENINGSDATUM
        def _tuple_from(source: dict, prefix: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
            return (
                source.get(f"{prefix}_year"),
                source.get(f"{prefix}_month"),
                source.get(f"{prefix}_day"),
            )

        opening_wd = (
            wikidata_struct.get("opening_year"),
            wikidata_struct.get("opening_month"),
            wikidata_struct.get("opening_day"),
        )
        opening_ai = (
            structured_ai.get("opening_year"),
            structured_ai.get("opening_month"),
            structured_ai.get("opening_day"),
        )

        # Prefer Wikidata if it has at least a year
        new_opening = None
        if any(v is not None for v in opening_wd):
            new_opening = opening_wd
        elif any(v is not None for v in opening_ai):
            new_opening = opening_ai

        current_opening = (
            self.park.opening_year,
            self.park.opening_month,
            self.park.opening_day,
        )
        if new_opening and new_opening != current_opening:
            updated_data["opening_year"] = new_opening[0]
            updated_data["opening_month"] = new_opening[1]
            updated_data["opening_day"] = new_opening[2]

        # COÖRDINATEN
        lat_wd = wikidata_struct.get("latitude")
        lon_wd = wikidata_struct.get("longitude")
        lat_ai = structured_ai.get("latitude")
        lon_ai = structured_ai.get("longitude")

        lat_new = lat_wd if lat_wd is not None else lat_ai
        lon_new = lon_wd if lon_wd is not None else lon_ai

        if lat_new is not None and lat_new != self.park.latitude:
            updated_data["latitude"] = lat_new
        if lon_new is not None and lon_new != self.park.longitude:
            updated_data["longitude"] = lon_new

        # WEBSITE
        site_wd = wikidata_struct.get("website_url")
        site_ai = structured_ai.get("website_url")
        site_new = site_wd or site_ai
        if site_new and site_new != self.park.website_url:
            updated_data["website_url"] = site_new

        # 5. Diff bepalen – future-proof
        diff = create_suggestion_diff(current_data, updated_data)

        if not diff:
            return {
                "message": "Geen nieuwe informatie gevonden in deze URL.",
                "source_page_id": source_page.id,
            }

        # 6. DataSuggestion aanmaken
        suggestion = models.DataSuggestion(
            entity_type="park",
            entity_id=self.park.id,
            current_data=current_data,
            suggested_data=diff,
            source_url=url,
        )

        self.db.add(suggestion)
        self.db.commit()
        self.db.refresh(suggestion)

        return {
            "message": "Extractie voor park voltooid (Wikidata + Wikipedia + AI + heuristiek).",
            "suggestion_id": suggestion.id,
            "source_page_id": source_page.id,
            "suggested_data": diff,
        }
