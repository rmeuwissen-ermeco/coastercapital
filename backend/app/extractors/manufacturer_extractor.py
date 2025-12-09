from __future__ import annotations

from typing import Dict, Any, List

from bs4 import BeautifulSoup, Tag

from .base_extractor import BaseExtractor


class ManufacturerExtractor(BaseExtractor):
    """
    Extractor voor manufacturers.

    Doel:
    - Officiële naam zo goed mogelijk vinden (schema.org, og:site_name, og:title, title)
    - Land-code voorzichtig afleiden uit adres/headquarters informatie
    - Korte beschrijving voor 'notes' maken op basis van about/company-sectie

    Belangrijk:
    - We vullen alleen velden in die we met redelijke zekerheid weten
    - Geen nieuwe velden introduceren, alleen: name, country_code, notes
    """

    def extract(self, soup: BeautifulSoup, text: str) -> Dict[str, Any]:
        suggested: Dict[str, Any] = {}

        name = self._extract_name(soup)
        if name:
            suggested["name"] = name

        country_code = self._extract_country_code(soup, text)
        if country_code:
            suggested["country_code"] = country_code

        notes = self._extract_notes(soup, text)
        if notes:
            suggested["notes"] = notes

        return suggested

    # ------------------------------------------------------------------
    # 1) Naam
    # ------------------------------------------------------------------
    def _extract_name(self, soup: BeautifulSoup) -> str | None:
        """
        Probeer de officiële bedrijfsnaam te vinden met een aantal strategieën:
        1. schema.org Organization → itemprop="name"
        2. og:site_name
        3. og:title
        4. <title> met simpele opschoning
        """

        # 1) schema.org Organization
        org_blocks: List[Tag] = soup.find_all(
            attrs={"itemtype": lambda v: v and "Organization" in v}
        )
        for org in org_blocks:
            name_tag = org.find(attrs={"itemprop": "name"})
            if name_tag and name_tag.get_text(strip=True):
                return name_tag.get_text(strip=True)

        # 2) og:site_name
        og_site_name = soup.find("meta", attrs={"property": "og:site_name"})
        if og_site_name and og_site_name.get("content"):
            name = og_site_name["content"].strip()
            if name:
                return name

        # 3) og:title
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content"):
            raw = og_title["content"].strip()
            cleaned = self._cleanup_title(raw)
            if cleaned:
                return cleaned

        # 4) fallback: <title>
        title_tag = soup.find("title")
        if title_tag:
            raw_title = title_tag.get_text().strip()
            cleaned = self._cleanup_title(raw_title)
            if cleaned:
                return cleaned

        return None

    def _cleanup_title(self, raw_title: str) -> str:
        """
        Titel opschonen door simpele scheidingstekens weg te knippen.
        Voorbeeld:
        - "Vekoma Rides – Official Website" -> "Vekoma Rides"
        - "Vekoma | Coasters & Rides" -> "Vekoma"
        """

        # splitsen op veel gebruikte scheidingstekens
        parts = (
            raw_title.split(" | ")[0]
            .split(" – ")[0]
            .split(" - ")[0]
            .strip()
        )
        return parts or raw_title.strip()

    # ------------------------------------------------------------------
    # 2) Land-code
    # ------------------------------------------------------------------
    def _extract_country_code(self, soup: BeautifulSoup, text: str) -> str | None:
        """
        Probeer voorzichtig een land-code te bepalen.

        Strategie:
        - Eerst kijken naar regels waarin woorden als 'headquarters', 'based in',
          'located in' voorkomen, en daarbinnen naar landnamen zoeken.
        - Pas als dat niets oplevert eventueel fallback naar globale tekst.
        - Beter geen land invullen dan een verkeerde land-code.
        """

        country_map = {
            "netherlands": "NL",
            "nederland": "NL",
            "germany": "DE",
            "deutschland": "DE",
            "belgium": "BE",
            "belgië": "BE",
            "belgie": "BE",
            "france": "FR",
            "frankrijk": "FR",
            "united kingdom": "GB",
            "great britain": "GB",
            "england": "GB",
            "united states": "US",
            "usa": "US",
            "u.s.a": "US",
            "u.s.a.": "US",
            "italy": "IT",
            "italië": "IT",
            "italie": "IT",
            "spain": "ES",
            "españa": "ES",
            "spanje": "ES",
        }

        lower_text = text.lower()
        lines = [line.strip() for line in lower_text.splitlines() if line.strip()]

        # Woorden die duiden op hoofdvestiging/adres
        hq_keywords = [
            "headquarters",
            "head office",
            "based in",
            "located in",
            "registered office",
            "office in",
            "headquarter",
        ]

        # 1) Eerst: regels met hq-keywords
        candidate_scores: Dict[str, int] = {}

        for line in lines:
            if any(k in line for k in hq_keywords):
                for phrase, code in country_map.items():
                    if phrase in line:
                        candidate_scores[code] = candidate_scores.get(code, 0) + 2

        if candidate_scores:
            # Kies het land met de hoogste score
            best_code = max(candidate_scores, key=candidate_scores.get)
            # Alleen invullen als we een duidelijke winnaar hebben
            if candidate_scores[best_code] >= 2:
                return best_code

        # 2) Fallback: zoeken in contact/adres blokken in HTML
        #    We kijken naar <address> en elementen met 'contact' in de id/class.
        address_candidates: List[str] = []

        for addr in soup.find_all("address"):
            address_candidates.append(addr.get_text(separator=" ", strip=True))

        for el in soup.find_all(True, attrs={"id": True}):
            if "contact" in el["id"].lower():
                address_candidates.append(el.get_text(separator=" ", strip=True))

        for el in soup.find_all(True, attrs={"class": True}):
            classes = " ".join(el.get("class", [])).lower()
            if "contact" in classes or "address" in classes:
                address_candidates.append(
                    el.get_text(separator=" ", strip=True)
                )

        candidate_scores = {}
        for block in address_candidates:
            block_lower = block.lower()
            for phrase, code in country_map.items():
                if phrase in block_lower:
                    candidate_scores[code] = candidate_scores.get(code, 0) + 1

        if candidate_scores:
            best_code = max(candidate_scores, key=candidate_scores.get)
            if candidate_scores[best_code] >= 1:
                return best_code

        # 3) Uiteindelijk: liever geen gok dan een foute waarde
        return None

    # ------------------------------------------------------------------
    # 3) Notes / beschrijving
    # ------------------------------------------------------------------
    def _extract_notes(self, soup: BeautifulSoup, text: str) -> str | None:
        """
        Maak een korte beschrijving van het bedrijf.

        Voorkeur:
        1. Tekst direct onder een 'About'/bedrijfsheadings
        2. meta description
        3. Eerste 1-3 zinnige paragrafen
        """

        # 1) Probeer een "About"/"Over ons" sectie te vinden
        about_text = self._extract_about_section(soup)
        if about_text:
            return about_text[:800]  # limiteren

        # 2) meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            desc = meta_desc["content"].strip()
            if desc:
                return desc[:800]

        # 3) eerste 1-3 paragrafen
        paragraphs = [
            p.get_text(separator=" ", strip=True)
            for p in soup.find_all("p")
            if p.get_text(strip=True)
        ]

        joined = ""
        for p in paragraphs:
            if len(joined) > 0:
                joined += " "
            joined += p
            if len(joined) >= 400:
                break

        if joined:
            return joined[:800]

        return None

    def _extract_about_section(self, soup: BeautifulSoup) -> str | None:
        """
        Zoekt naar headings zoals 'About', 'About us', 'Over ons', 'Über uns', 'The company'
        en pakt 1–3 paragrafen erna.
        """

        about_keywords = [
            "about",
            "about us",
            "about us.",
            "about the company",
            "the company",
            "over ons",
            "über uns",
            "über uns.",
            "company profile",
        ]

        # Zoek h1–h3 headings
        for level in ["h1", "h2", "h3"]:
            for heading in soup.find_all(level):
                heading_text = heading.get_text(separator=" ", strip=True).lower()
                if any(k in heading_text for k in about_keywords):
                    # verzamel de volgende siblings/paragrafen
                    paragraphs: List[str] = []
                    current: Tag | None = heading

                    # loop door volgende siblings, maar niet eindeloos
                    for _ in range(10):
                        if current is None:
                            break
                        current = current.find_next_sibling()
                        if current is None:
                            break
                        if current.name == "p":
                            txt = current.get_text(separator=" ", strip=True)
                            if txt:
                                paragraphs.append(txt)
                        # stoppen als we een nieuwe heading tegenkomen
                        if current.name in ["h1", "h2", "h3"]:
                            break

                    if paragraphs:
                        combined = " ".join(paragraphs)
                        if combined:
                            return combined

        return None
