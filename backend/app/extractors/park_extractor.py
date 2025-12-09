import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from .. import models
from ..ai.client import summarize_company_text
from ..routers.utils import create_suggestion_diff


class ParkExtractor:
    """
    Extractor voor parks:
    - HTML ophalen via park.website_url
    - SourcePage aanmaken (logging & herbruikbare bron)
    - Heuristieken (title/meta) als backup
    - LLM gebruiken om een nette beschrijving (notes) te genereren
    - DataSuggestion aanmaken met alleen de velden die écht veranderen
    """

    def __init__(self, db: Session, park: models.Park):
        self.db = db
        self.park = park

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
        """Slaat de bronpagina op in SourcePage en geeft het record terug."""
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

    def _heuristic_name(self, soup: BeautifulSoup) -> str | None:
        """Eenvoudige poging om een betere naam uit <title> te halen."""
        title_tag = soup.find("title")
        if not title_tag:
            return None
        title_text = title_tag.get_text().strip()
        if not title_text or title_text == self.park.name:
            return None
        return title_text

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

    def _extract_notes_with_ai(self, text: str) -> str | None:
        """
        Maakt een AI-samenvatting gericht op het park en zijn rol in de wereld van
        pretparken / coasters. Heuristiek blijft backup.
        """
        # Tekst wat bijsnijden, anders voeren we te veel in
        truncated = text[:15000]

        base_text = (
            "You are helping to maintain a knowledge base about theme parks and roller coasters.\n\n"
            "Task:\n"
            "- Summarize the company or park behind this website.\n"
            "- Focus on what type of park it is, what visitors can expect, and its role in the amusement industry.\n"
            "- If the text clearly indicates relationships with roller coasters (well-known rides, manufacturers, ride types), "
            "describe these briefly and factually.\n"
            "- Do NOT invent coasters or manufacturers; only mention them if they are clearly present in the text.\n\n"
            "Style:\n"
            "- Neutral, factual, accessible.\n"
            "- Suitable for a public knowledge base and search engines.\n"
            "- No marketing language or hype, no subjective judgements.\n"
            "- Use clear sentences and a concise paragraph-style summary.\n\n"
            "Input text (may be noisy website content):\n"
            "--------------------\n"
            f"{truncated}\n"
            "--------------------\n"
        )

        try:
            ai_summary = summarize_company_text(
                base_text,
                language="en",
                max_chars=800,
            )
        except Exception:
            # Als de AI-call faalt, geen crash – dan valt de extractor terug op heuristiek.
            return None

        if ai_summary is None:
            return None

        # We houden het simpel: de helper geeft nu al een net stuk tekst terug.
        # Mocht dit ooit een dict worden, kunnen we hier uitbreiden.
        return str(ai_summary).strip() or None

    def run(self) -> dict:
        """
        Voert de volledige extractie uit en maakt eventueel een DataSuggestion aan.
        Geeft een klein resultaat-dict terug.
        """

        if not self.park.website_url:
            raise ValueError("Geen website_url bekend voor dit park.")

        url = self.park.website_url

        # 1. HTML ophalen
        status_code, raw_html = self._fetch_html(url)

        # 2. Soup + plain text
        soup = BeautifulSoup(raw_html, "html.parser")
        clean_text = soup.get_text(separator="\n").strip()

        # 3. SourcePage loggen
        source_page = self._store_source_page(
            url=url,
            status_code=status_code,
            raw_html=raw_html,
            clean_text=clean_text,
        )

        # 4. Candidate updates voorbereiden
        current_data = {
            "name": self.park.name,
            "country_code": self.park.country_code,
            "website_url": self.park.website_url,
            "notes": self.park.notes,
        }

        updated_data = dict(current_data)

        # 4a. Heuristische naam
        new_name = self._heuristic_name(soup)
        if new_name:
            updated_data["name"] = new_name

        # 4b. AI-samenvatting proberen
        ai_notes = self._extract_notes_with_ai(clean_text)

        # Als AI faalt of niks bruikbaars geeft, vallen we terug op meta-description
        if ai_notes:
            updated_data["notes"] = ai_notes
        else:
            heuristic_notes = self._heuristic_notes(soup)
            if heuristic_notes:
                updated_data["notes"] = heuristic_notes

        # 5. Diff bepalen – future-proof: ook toekomstige velden worden hier meegenomen
        diff = create_suggestion_diff(current_data, updated_data)

        if not diff:
            # Niets nieuws – maar we hebben wél een SourcePage gelogd
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
            "message": "Extractie voor park voltooid (AI + heuristiek).",
            "suggestion_id": suggestion.id,
            "source_page_id": source_page.id,
            "suggested_data": diff,
        }
