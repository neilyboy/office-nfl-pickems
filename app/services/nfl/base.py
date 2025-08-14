from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional


@dataclass
class ProviderTeam:
    abbr: str
    name: str
    location: str
    slug: Optional[str] = None
    alt_abbrs: Optional[List[str]] = None
    logo_path: Optional[str] = None  # URL or app-static path


@dataclass
class ProviderGame:
    home_abbr: str
    away_abbr: str
    start_time: datetime  # must be timezone-aware UTC
    provider_game_id: Optional[str] = None


class NFLProvider:
    """Abstract provider interface for fetching NFL data."""

    def name(self) -> str:
        raise NotImplementedError

    def get_teams(self) -> Iterable[ProviderTeam]:
        raise NotImplementedError

    def get_week_schedule(self, season_year: int, week_number: int, season_type: int = 2) -> Iterable[ProviderGame]:
        """Return games for a given season/week.

        - Times must be timezone-aware UTC.
        - season_type follows ESPN semantics: 1=Preseason, 2=Regular (default), 3=Postseason.
        - Return an empty iterable if unsupported.
        """
        return []
