from __future__ import annotations

from app.core.config import get_settings
from .base import NFLProvider
from .local_dict import LocalDictProvider
from .espn import ESPNScoreboardProvider


def get_provider() -> NFLProvider:
    settings = get_settings()
    key = (settings.NFL_PROVIDER or "local_dict").lower()
    if key == "local_dict":
        return LocalDictProvider()
    if key == "espn":
        return ESPNScoreboardProvider()
    # Future: add mappings for nfl, other providers, etc.
    return LocalDictProvider()
