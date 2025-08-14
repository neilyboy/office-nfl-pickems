from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, List, Optional

import httpx

from app.core.config import get_settings
from .base import NFLProvider, ProviderGame, ProviderTeam
from .local_dict import LocalDictProvider

logger = logging.getLogger(__name__)


class ESPNScoreboardProvider(NFLProvider):
    """ESPN public scoreboard-based provider.

    - Teams: delegates to LocalDictProvider for canonical team data.
    - Schedule: fetched from ESPN scoreboard JSON.
    """

    def __init__(self) -> None:
        self._teams_delegate = LocalDictProvider()
        # Default to ESPN public site scoreboard endpoint; can be overridden via NFL_API_BASE
        self._base = get_settings().NFL_API_BASE or "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        self._teams_base = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"

    def name(self) -> str:
        return "espn"

    def get_teams(self) -> Iterable[ProviderTeam]:
        """Fetch teams (with logo URLs) from ESPN teams API.

        Falls back to LocalDictProvider on error.
        """
        teams: List[ProviderTeam] = []
        try:
            with httpx.Client(timeout=10) as client:
                # Limit param ensures full list
                resp = client.get(self._teams_base, params={"limit": "100"})
                resp.raise_for_status()
                data = resp.json()

            raw_teams = []
            # ESPN returns different shapes depending on endpoint
            if isinstance(data, dict):
                if "teams" in data and isinstance(data["teams"], list):
                    raw_teams = data["teams"]
                else:
                    sports = (data.get("sports") or [])
                    if sports:
                        leagues = (sports[0].get("leagues") or [])
                        if leagues:
                            raw_teams = leagues[0].get("teams") or []

            for item in raw_teams:
                t = item.get("team") if isinstance(item, dict) else None
                if not t:
                    t = item if isinstance(item, dict) else None
                if not t:
                    continue
                abbr = (t.get("abbreviation") or "").upper()
                if not abbr:
                    continue
                location = t.get("location") or ""
                name = t.get("name") or t.get("displayName") or abbr
                logos = t.get("logos") or []
                logo_path = None
                if isinstance(logos, list) and logos:
                    # Prefer first logo href
                    href = logos[0].get("href") if isinstance(logos[0], dict) else None
                    if href:
                        logo_path = href
                teams.append(ProviderTeam(abbr=abbr, name=name, location=location, slug=abbr.lower(), alt_abbrs=None, logo_path=logo_path))

            # If ESPN returned nothing, fallback to local list
            if not teams:
                return list(self._teams_delegate.get_teams())
            return teams
        except Exception as e:
            logger.warning("ESPN get_teams failed: %s", e)
            return list(self._teams_delegate.get_teams())

    def get_week_schedule(self, season_year: int, week_number: int, season_type: int = 2) -> Iterable[ProviderGame]:
        # ESPN public scoreboard typically expects 'year', 'week', and 'seasontype'.
        # We will try the given season year first, then the following calendar year as a fallback
        # to cover January games (late regular season and postseason).
        base_params = {
            "year": str(season_year),
            "week": str(week_number),
            # 1=Preseason, 2=Regular, 3=Postseason
            "seasontype": str(season_type),
        }
        games: List[ProviderGame] = []

        # Try candidate years to cover New Year boundary.
        candidate_years = [season_year, season_year + 1]
        events = []
        params_used: Optional[dict] = None
        last_exc: Optional[Exception] = None
        try:
            with httpx.Client(timeout=10) as client:
                for y in candidate_years:
                    p = dict(base_params)
                    p["year"] = str(y)
                    try:
                        resp = client.get(self._base, params=p)
                        resp.raise_for_status()
                        data = resp.json()
                        evs = data.get("events") or []
                        logger.debug("ESPN scoreboard query params=%s returned %d events", p, len(evs))
                        if evs:
                            events = evs
                            params_used = p
                            break
                        # Fallback attempt: try using 'dates' param (YYYY) if no events via 'year'
                        p2 = dict(base_params)
                        p2.pop("year", None)
                        p2["dates"] = str(y)
                        try:
                            resp2 = client.get(self._base, params=p2)
                            resp2.raise_for_status()
                            data2 = resp2.json()
                            evs2 = data2.get("events") or []
                            logger.debug("ESPN scoreboard query (fallback) params=%s returned %d events", p2, len(evs2))
                            if evs2:
                                events = evs2
                                params_used = p2
                                break
                        except Exception as e2:
                            last_exc = e2
                            logger.debug("ESPN fallback fetch failed for params=%s: %s", p2, e2)
                    except Exception as e:
                        last_exc = e
                        logger.debug("ESPN fetch attempt failed for params=%s: %s", p, e)
        except Exception as e:
            logger.warning("ESPN provider fetch failed (client error): %s", e)
            return games

        if not events:
            if last_exc:
                logger.warning("ESPN provider returned no events; last error: %s (tried years=%s)", last_exc, candidate_years)
            else:
                logger.warning("ESPN provider returned no events for params tried (years=%s)", candidate_years)
            return games

        logger.debug("ESPN scoreboard events=%d for params=%s", len(events), params_used or base_params)
        for ev in events:
            try:
                comps = (ev.get("competitions") or [])
                if not comps:
                    continue
                comp = comps[0]
                date_str = comp.get("date") or ev.get("date")
                if not date_str:
                    continue
                # Normalize ISO 8601 with Z -> +00:00
                dt = _parse_iso_utc(date_str)
                competitors = comp.get("competitors") or []
                home_abbr = None
                away_abbr = None
                for c in competitors:
                    team = c.get("team") or {}
                    abbr = (team.get("abbreviation") or "").upper()
                    if c.get("homeAway") == "home":
                        home_abbr = abbr
                    elif c.get("homeAway") == "away":
                        away_abbr = abbr
                if not home_abbr or not away_abbr:
                    continue
                provider_game_id = str(ev.get("id")) if ev.get("id") else None
                games.append(ProviderGame(home_abbr=home_abbr, away_abbr=away_abbr, start_time=dt, provider_game_id=provider_game_id))
            except Exception as e:
                logger.debug("Skipping event due to parse error: %s", e)
                continue

        return games


def _parse_iso_utc(s: str) -> datetime:
    try:
        # Handle Zulu time
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        # Fallback: return now UTC
        return datetime.now(timezone.utc)
