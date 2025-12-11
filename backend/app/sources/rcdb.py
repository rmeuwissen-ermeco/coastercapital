from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def find_rcdb_page_for_name(name: str) -> Optional[None]:
    logger.info("[RCDB] Disabled lookup for %r", name)
    return None
