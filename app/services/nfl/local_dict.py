from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Optional

from .base import NFLProvider, ProviderTeam, ProviderGame


class LocalDictProvider(NFLProvider):
    """Local static dictionary provider for teams.

    Schedules are not provided by this provider (returns empty schedule).
    """

    def name(self) -> str:
        return "local_dict"

    def get_teams(self) -> Iterable[ProviderTeam]:
        teams: List[ProviderTeam] = [
            ProviderTeam("ARI", "Cardinals", "Arizona", alt_abbrs=["ARZ"]),
            ProviderTeam("ATL", "Falcons", "Atlanta"),
            ProviderTeam("BAL", "Ravens", "Baltimore"),
            ProviderTeam("BUF", "Bills", "Buffalo"),
            ProviderTeam("CAR", "Panthers", "Carolina"),
            ProviderTeam("CHI", "Bears", "Chicago"),
            ProviderTeam("CIN", "Bengals", "Cincinnati"),
            ProviderTeam("CLE", "Browns", "Cleveland"),
            ProviderTeam("DAL", "Cowboys", "Dallas"),
            ProviderTeam("DEN", "Broncos", "Denver"),
            ProviderTeam("DET", "Lions", "Detroit"),
            ProviderTeam("GB", "Packers", "Green Bay", alt_abbrs=["GNB"]),
            ProviderTeam("HOU", "Texans", "Houston"),
            ProviderTeam("IND", "Colts", "Indianapolis"),
            ProviderTeam("JAX", "Jaguars", "Jacksonville", alt_abbrs=["JAC"]),
            ProviderTeam("KC", "Chiefs", "Kansas City"),
            ProviderTeam("LAC", "Chargers", "Los Angeles", alt_abbrs=["SD"]),
            ProviderTeam("LAR", "Rams", "Los Angeles", alt_abbrs=["LA", "STL"]),
            ProviderTeam("LV", "Raiders", "Las Vegas", alt_abbrs=["OAK"]),
            ProviderTeam("MIA", "Dolphins", "Miami"),
            ProviderTeam("MIN", "Vikings", "Minnesota"),
            ProviderTeam("NE", "Patriots", "New England", alt_abbrs=["NWE"]),
            ProviderTeam("NO", "Saints", "New Orleans", alt_abbrs=["NOR"]),
            ProviderTeam("NYG", "Giants", "New York"),
            ProviderTeam("NYJ", "Jets", "New York"),
            ProviderTeam("PHI", "Eagles", "Philadelphia"),
            ProviderTeam("PIT", "Steelers", "Pittsburgh"),
            ProviderTeam("SEA", "Seahawks", "Seattle"),
            ProviderTeam("SF", "49ers", "San Francisco", alt_abbrs=["SFO"]),
            ProviderTeam("TB", "Buccaneers", "Tampa Bay"),
            ProviderTeam("TEN", "Titans", "Tennessee"),
            ProviderTeam("WAS", "Commanders", "Washington", alt_abbrs=["WSH"]),
        ]
        # Slug default is lower-case abbr and assign default offline logo path
        for t in teams:
            t.slug = (t.slug or t.abbr.lower())
            t.logo_path = f"/static/logos/{t.abbr.upper()}.svg"
        return teams

    def get_week_schedule(self, season_year: int, week_number: int, season_type: int = 2) -> Iterable[ProviderGame]:
        # Not provided by local static provider
        return []
