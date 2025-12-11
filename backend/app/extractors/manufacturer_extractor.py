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


# Heel simpele country-name → ISO2 mapping voor de meest relevante landen.
# Dit voorkomt dat we meteen weer een aparte AI-call moeten doen.
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
    - HTML ophalen via manufacturer.website_url
    - SourcePage aanmaken voor de officiële site
    - AI-call 1: kernfeiten uit de officiële site (naam, land, ride_types, coasters, ...)
    - Wikipedia ophalen en filteren op kernwoorden/coasternamen
    - AI-call 2: multi-source samenvatting met focus op rollen in de coasterwereld (notes)
    - Gestructureerde correcties voorstellen voor:
        - name
        - country_code
      (later uit te breiden met extra velden als die in het model komen)
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
        Voor manufacturers loggen we alleen de officiële site + Wikipedia.
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
        Wordt alleen gebruikt als AI of Wikipedia geen nettere naam geven.
        """
        title_tag = soup.find("title")
        if not title_tag:
            return None
        title_text = title_tag.get_text().strip()
        if not title_text or title_text == self.manufacturer.name:
            return None
        return title_text

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
        keywords: list[str],
        coaster_names: list[str],
    ) -> SourceSnippet | None:
        """
        Haalt Wikipedia-extract op, filtert zinnen op kernwoorden/coasternamen
        en slaat de bron op als SourcePage.
        """
        # We zoeken op de huidige naam; als AI een betere naam vindt, kan dat later nog aangepast worden
        page = find_best_wikipedia_page(self.manufacturer.name)
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

    def _extract_notes_with_ai(self, snippets: list[SourceSnippet]) -> str | None:
        """
        AI-call 2: multi-source samenvatting over de manufacturer met focus op
        producten, ride_types en rol in de coasterwereld.
        """
        if not snippets:
            return None

        # Bepaal een nette naam om in de prompt te gebruiken
        base_name = self.manufacturer.name or "Unknown manufacturer"

        try:
            ai_summary = summarize_entity_from_sources(
                name=base_name,
                entity_type="manufacturer",
                sources=snippets,
                language="en",
                max_chars=800,
            )
        except Exception:
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

        # 4a. AI-call 1: kernfeiten uit de officiële site
        facts = self._extract_keywords_from_official(clean_text)
        keywords = facts.get("keywords", []) or []
        notable_coasters = facts.get("notable_coasters", []) or []

        # Voeg de huidige naam toe als keyword
        if self.manufacturer.name:
            keywords.append(self.manufacturer.name)

        # 4b. Feitenblok als extra bron
        facts_lines: list[str] = []
        if facts.get("name"):
            facts_lines.append(f"Name: {facts['name']}")
        if facts.get("location_country"):
            facts_lines.append(f"Country: {facts['location_country']}")
        if facts.get("opening_year"):
            facts_lines.append(f"Founded/opening year: {facts['opening_year']}")
        if facts.get("ride_types"):
            facts_lines.append(
                "Ride types: " + ", ".join(facts["ride_types"][:20])
            )
        if notable_coasters:
            facts_lines.append(
                "Notable coasters: " + ", ".join(notable_coasters[:25])
            )

        facts_text = "\n".join(facts_lines).strip() if facts_lines else ""

        # 4c. Bron-snippets opbouwen: official + facts + Wikipedia
        snippets: list[SourceSnippet] = []

        # Officiële website
        official_snippet = self._get_official_snippet(clean_text, url)
        snippets.append(official_snippet)

        # Feiten uit AI-call 1
        if facts_text:
            facts_snippet = SourceSnippet(
                label="Extracted facts from official website (AI)",
                text=facts_text,
                url=None,
            )
            snippets.append(facts_snippet)

        # Wikipedia (optioneel)
        wiki_snippet = self._get_wikipedia_snippet(
            keywords=keywords,
            coaster_names=notable_coasters,
        )
        if wiki_snippet:
            snippets.append(wiki_snippet)

        # 4d. AI-samenvatting (notes) over alle bronnen
        ai_notes = self._extract_notes_with_ai(snippets)
        if ai_notes:
            updated_data["notes"] = ai_notes

        # 4e. Gestructureerde correcties op basis van AI-facts
        # Naam: gebruik AI-naam als die netter/canonischer is
        name_new = facts.get("name")
        if name_new and name_new != self.manufacturer.name:
            updated_data["name"] = name_new

        # Landcode: uit location_country proberen een ISO2 te halen
        country_raw = facts.get("location_country")
        country_code_new = _normalize_country_to_iso2(country_raw)
        if country_code_new and country_code_new != self.manufacturer.country_code:
            updated_data["country_code"] = country_code_new

        # Voor nu laten we website_url ongemoeid; die komt uit je eigen invoer.
        # Later kunnen we, als we Wikipedia/Wikidata erbij nemen, een extra check toevoegen.

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
            "message": "Extractie voor manufacturer voltooid (AI multi-source + heuristiek).",
            "suggestion_id": suggestion.id,
            "source_page_id": source_page.id,
            "suggested_data": diff,
        }
