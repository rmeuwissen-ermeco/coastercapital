from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any
from bs4 import BeautifulSoup


class BaseExtractor(ABC):
    """
    Basis-klasse voor extractors.

    Elke extractor:
    - krijgt BeautifulSoup + plain text
    - retourneert een dict met velden die bij het Pydantic-model horen
      (bv. name, country_code, notes)
    """

    @abstractmethod
    def extract(self, soup: BeautifulSoup, text: str) -> Dict[str, Any]:
        ...
