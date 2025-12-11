import logging
import re
import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from .. import models
from ..ai.client import (
    SourceSnippet,
    summarize_entity_from_sources,
    extract_manufacturer_facts_from_text,
)
from ..routers.utils import create_suggestion_diff
from ..sources.wikipedia import find_best_wikipedia_page
from ..sources.wikidata import (
    find_wikidata_for_name,
    parse_wikidata_manufacturer_entity,
)

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


# Heel simpele country-name → ISO2 mapping voor fallback op basis van AI-facts
_COUNTRY_NAME_TO_ISO = {
    "netherlands": "NL",
    "the netherlands": "NL",
    "kingdom of the netherlands": "NL",
    "germany": "DE",
    "federal republic of germany": "DE",
    "switzerland": "CH",
    "swiss": "CH",
    "poland": "PL",
    "france": "FR",
    "spain": "ES",
    "italy": "IT",
    "belgium": "BE",
    "united kingdom": "GB",
    "great britain": "GB",
    "england": "GB",
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "canada": "CA",
    "china": "CN",
    "japan": "JP",
}


def _normalize_country_to_iso2(raw: str | None) -> str | None:
    """
    Probeert een landnaam of code om te zetten naar een ISO2 country_code.
    - Als het al 'NL', 'DE', ... is -> uppercased teruggeven.
    - Als het een naam is -> simpele mapping op basis van _COUNTRY_NAME_TO_ISO.
    """
    if not raw:
        return None

    value = raw.strip()
    if not value:
        return None

    # Als het al een 2-letterig ding is
    if len(value) == 2 and value.isalpha():
        return value.upper()

    key = value.lower()
    return _COUNTRY_NAME_TO_ISO.get(key)


class ManufacturerExtractor:
    """
    Extractor voor manufacturers:
    - Wikidata als primaire bron
    - Wikipedia als tweede bron
    - Officiële website als derde bron
    - Heuristiek (title/meta) als uiterste fallback voor naam/notes

    Flow:
    - HTML ophalen via manufacturer.website_url
    - SourcePage aanmaken voor de officiële site
    - Wikidata ophalen voor structured data (naam, land, opening, website)
    - AI-call 1: kernfeiten uit de officiële site (naam, land, ride_types, coasters, ...)
    - Wikipedia ophalen en filteren op kernwoorden/coasternamen
    - AI-call 2: multi-source samenvatting met focus op rol in coasterwereld (notes)
    - Gestructureerde correcties voorstellen voor:
        - name
        - country_code
        - website_url
    - create_suggestion_diff zorgt dat alleen echte wijzigingen in DataSuggestion komen
    """

    def __init__(self, db: Session, manufacturer: models.Manufacturer):
        self.db = db
        self.manufacturer = manufacturer

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
        We loggen in ieder geval de officiële site; Wikipedia/Wikidata kunnen later
        ook worden toegevoegd als extra transparantie.
        """
        source_page = models.SourcePage(
            entity_type="manufacturer",
            entity_id=self.manufacturer.id,
            url=url,
            status_code=status_code,
            raw_html=raw_html[:10000],
            clean_text=clean_text[:10000],
        )
        self.db.add(source_page)
        self.db.commit()
        self.db.refresh(source_page)
        return source_page

    def _heuristic_name_from_title(self, soup: BeautifulSoup) -> str | None:
        """
        Eenvoudige poging om een betere naam uit <title> te halen.
        Wordt alleen gebruikt als AI/Wikidata/Wikipedia geen nettere naam geven.
        """
        title_tag = soup.find("title")
        if not title_tag:
            return None
        title_text = title_tag.get_text().strip()
        if not title_text or title_text == self.manufacturer.name:
            return None
        return title_text

    def _heuristic_notes(self, soup: BeautifulSoup) -> str | None:
        """
        Heuristische beschrijving op basis van meta description of og:description.
        Alleen als AI niets bruikbaars oplevert.
        """
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if not meta_desc:
            meta_desc = soup.find("meta", attrs={"property": "og:description"})

        if not meta_desc:
            return None

        text = (meta_desc.get("content") or "").strip()
        if not text:
            return None

        if text == (self.manufacturer.notes or ""):
            return None

        return text

    def _extract_keywords_from_official(self, text: str) -> dict:
        """
        AI-call 1: haal kernfeiten, kernwoorden, ride_types en coasternamen uit de officiële site.
        Bij fout of ontbrekende info krijg je een lege dict.
        """
        facts = extract_manufacturer_facts_from_text(text, language="en") or {}
        return {
            "name": facts.get("name"),
            "location_country": facts.get("location_country"),
            "opening_year": facts.get("opening_year"),
            "keywords": facts.get("keywords") or [],
            "ride_types": facts.get("ride_types") or [],
            "notable_coasters": facts.get("notable_coasters") or [],
            "notable_parks": facts.get("notable_parks") or [],
        }

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
        search_name: str,
        keywords: list[str],
        coaster_names: list[str],
    ) -> SourceSnippet | None:
        """
        Haalt Wikipedia-extract op, filtert zinnen op kernwoorden/coasternamen
        en slaat de bron op als SourcePage.
        """
        page = find_best_wikipedia_page(search_name)
        if not page or not page.extract:
            return None

        filtered_text = _select_relevant_sentences(
            page.extract,
            keywords=keywords,
            coaster_names=coaster_names,
            max_sentences=80,
        )

        # Volledige extract in raw_html, gefilterde tekst in clean_text
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

    def _get_wikidata_structured_and_snippet(self) -> tuple[dict, SourceSnippet | None]:
        """
        Haalt Wikidata-info op voor deze manufacturer en bouwt een klein
        tekst-snippet voor gebruik in de multi-source samenvatting.
        """
        structured: dict = {}
        snippet: SourceSnippet | None = None

        name = self.manufacturer.name or ""
        if not name.strip():
            return structured, None

        try:
            entity = find_wikidata_for_name(name)
        except Exception as e:
            logger.error(
                "[ManufacturerExtractor] Wikidata lookup failed for %r: %s",
                name,
                e,
            )
            return structured, None

        if not entity:
            return structured, None

        structured = parse_wikidata_manufacturer_entity(entity) or {}
        lines: list[str] = []

        if structured.get("name"):
            lines.append(f"Name: {structured['name']}")
        if structured.get("country_code"):
            lines.append(f"Country code: {structured['country_code']}")
        if structured.get("opening_year"):
            y = structured["opening_year"]
            m = structured.get("opening_month")
            d = structured.get("opening_day")
            if m and d:
                lines.append(f"Founded/opening: {y:04d}-{m:02d}-{d:02d}")
            else:
                lines.append(f"Founded/opening year: {y}")
        if structured.get("website_url"):
            lines.append(f"Official website (Wikidata): {structured['website_url']}")

        text = "\n".join(lines).strip()
        if text:
            snippet = SourceSnippet(
                label="Wikidata",
                text=text,
                url=None,  # we kennen het exacte entity-URL hier niet, alleen de data
            )

        return structured, snippet

    def _extract_notes_with_ai(self, snippets: list[SourceSnippet]) -> str | None:
        """
        AI-call 2: multi-source samenvatting over de manufacturer met focus op
        producten, ride_types en rol in de coasterwereld.
        """
        if not snippets:
            return None

        base_name = self.manufacturer.name or "Unknown manufacturer"

        try:
            ai_summary = summarize_entity_from_sources(
                name=base_name,
                entity_type="manufacturer",
                sources=snippets,
                language="en",
                max_chars=800,
            )
        except Exception as e:
            logger.error(
                "[ManufacturerExtractor] Error in summarize_entity_from_sources: %s",
                e,
            )
            return None

        if not ai_summary:
            return None

        return str(ai_summary).strip() or None

    def run(self) -> dict:
        """
        Voert de volledige extractie uit en maakt eventueel een DataSuggestion aan.
        Geeft een klein resultaat-dict terug.
        """

        if not self.manufacturer.website_url:
            raise ValueError("Geen website_url bekend voor deze manufacturer.")

        url = self.manufacturer.website_url

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

        # 4. Candidate updates voorbereiden
        current_data = {
            "name": self.manufacturer.name,
            "country_code": self.manufacturer.country_code,
            "website_url": self.manufacturer.website_url,
            "notes": self.manufacturer.notes,
        }
        updated_data = dict(current_data)

        # 4a. Wikidata structured info + snippet
        wikidata_structured, wikidata_snippet = self._get_wikidata_structured_and_snippet()

        # 4b. AI-call 1: kernfeiten uit de officiële site
        facts = self._extract_keywords_from_official(clean_text)
        keywords = facts.get("keywords", []) or []
        notable_coasters = facts.get("notable_coasters", []) or []

        # Voeg de huidige naam én Wikidata-naam toe als keyword
        if self.manufacturer.name:
            keywords.append(self.manufacturer.name)
        if wikidata_structured.get("name"):
            keywords.append(wikidata_structured["name"])

        # Feitenblok als extra bron
        facts_lines: list[str] = []
        if facts.get("name"):
            facts_lines.append(f"Name (from website text): {facts['name']}")
        if facts.get("location_country"):
            facts_lines.append(f"Country (from website text): {facts['location_country']}")
        if facts.get("opening_year"):
            facts_lines.append(f"Founded/opening year (from website text): {facts['opening_year']}")
        if facts.get("ride_types"):
            facts_lines.append(
                "Ride types: " + ", ".join(facts["ride_types"][:20])
            )
        if notable_coasters:
            facts_lines.append(
                "Notable coasters (from website text): "
                + ", ".join(notable_coasters[:25])
            )

        facts_text = "\n".join(facts_lines).strip() if facts_lines else ""

        # 4c. Bron-snippets opbouwen in volgorde:
        # Wikidata -> Official site -> Facts -> Wikipedia
        snippets: list[SourceSnippet] = []

        if wikidata_snippet:
            snippets.append(wikidata_snippet)

        official_snippet = self._get_official_snippet(clean_text, url)
        snippets.append(official_snippet)

        if facts_text:
            facts_snippet = SourceSnippet(
                label="Extracted facts from official website (AI)",
                text=facts_text,
                url=None,
            )
            snippets.append(facts_snippet)

        # Wikipedia (optioneel) – we zoeken met Wikidata-naam als die bestaat, anders huidige naam
        search_name = wikidata_structured.get("name") or self.manufacturer.name or ""
        if search_name.strip():
            wiki_snippet = self._get_wikipedia_snippet(
                search_name=search_name,
                keywords=keywords,
                coaster_names=notable_coasters,
            )
            if wiki_snippet:
                snippets.append(wiki_snippet)

        # 4d. AI-samenvatting (notes) over alle bronnen
        ai_notes = self._extract_notes_with_ai(snippets)
        if ai_notes:
            updated_data["notes"] = ai_notes
        else:
            # fallback: heuristiek
            heuristic_notes = self._heuristic_notes(soup)
            if heuristic_notes:
                updated_data["notes"] = heuristic_notes

        # 4e. Gestructureerde correcties

        # Naam: voorkeur voor Wikidata-naam, anders AI-facts-naam
        canon_name = (
            wikidata_structured.get("name")
            or facts.get("name")
        )
        if canon_name and canon_name != self.manufacturer.name:
            updated_data["name"] = canon_name

        # Landcode: eerst Wikidata, dan fallback via AI-facts
        country_code_new = wikidata_structured.get("country_code")
        if not country_code_new and facts.get("location_country"):
            country_code_new = _normalize_country_to_iso2(facts.get("location_country"))

        if country_code_new and country_code_new != self.manufacturer.country_code:
            updated_data["country_code"] = country_code_new

        # Website: als Wikidata een andere (of ontbrekende) website heeft, voorstel maken
        website_new = wikidata_structured.get("website_url")
        if website_new and website_new != self.manufacturer.website_url:
            updated_data["website_url"] = website_new

        # 4f. Als alles faalt, kunnen we nog een heuristische naam uit <title> proberen
        if updated_data.get("name") == current_data.get("name"):
            new_name_from_title = self._heuristic_name_from_title(soup)
            if new_name_from_title and new_name_from_title != self.manufacturer.name:
                updated_data["name"] = new_name_from_title

        # 5. Diff bepalen – alleen velden die echt veranderen
        diff = create_suggestion_diff(current_data, updated_data)

        if not diff:
            return {
                "message": "Geen nieuwe informatie gevonden in deze URL.",
                "source_page_id": source_page.id,
            }

        # 6. DataSuggestion aanmaken
        suggestion = models.DataSuggestion(
            entity_type="manufacturer",
            entity_id=self.manufacturer.id,
            current_data=current_data,
            suggested_data=diff,
            source_url=url,
        )

        self.db.add(suggestion)
        self.db.commit()
        self.db.refresh(suggestion)

        return {
            "message": "Extractie voor manufacturer voltooid (Wikidata + Wikipedia + official + heuristiek).",
            "suggestion_id": suggestion.id,
            "source_page_id": source_page.id,
            "suggested_data": diff,
        }
