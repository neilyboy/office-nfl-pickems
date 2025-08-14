from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional
import time

import httpx
from app.core.config import get_settings

logger = logging.getLogger(__name__)

ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/v2/sports/football/nfl/summary"

# Simple in-memory cache for live summaries (per event)
_SETTINGS = get_settings()
_CACHE_TTL_SECONDS = max(1, int(getattr(_SETTINGS, "LIVE_CACHE_TTL_SECONDS", 15)))
_CACHE: Dict[str, tuple[float, LiveGame]] = {}
_NEGATIVE_TTL_SECONDS = max(1, int(getattr(_SETTINGS, "LIVE_NEGATIVE_TTL_SECONDS", 600)))
# Map event_id -> expiry epoch when we should try again (used for 404/410 results)
_NEG_CACHE: Dict[str, float] = {}


class LiveGame:
    def __init__(
        self,
        event_id: str,
        state: str,
        display_clock: Optional[str],
        period: Optional[int],
        home_score: Optional[int],
        away_score: Optional[int],
        possession: Optional[str] = None,  # 'home' | 'away' | None
        down_distance: Optional[str] = None,
        yard_line: Optional[str] = None,
        is_red_zone: Optional[bool] = None,
        home_timeouts: Optional[int] = None,
        away_timeouts: Optional[int] = None,
        last_play: Optional[str] = None,
        # Extra rich details (optional)
        home_record: Optional[str] = None,
        away_record: Optional[str] = None,
        venue_name: Optional[str] = None,
        venue_city: Optional[str] = None,
        venue_state: Optional[str] = None,
        weather: Optional[str] = None,
        network: Optional[str] = None,
        odds: Optional[str] = None,
        win_prob_home: Optional[float] = None,  # percent 0-100
        win_prob_away: Optional[float] = None,  # percent 0-100
        drive_summary: Optional[str] = None,
    ) -> None:
        self.event_id = event_id
        self.state = state  # pre | in | post
        self.display_clock = display_clock
        self.period = period
        self.home_score = home_score
        self.away_score = away_score
        self.possession = possession
        self.down_distance = down_distance
        self.yard_line = yard_line
        self.is_red_zone = is_red_zone
        self.home_timeouts = home_timeouts
        self.away_timeouts = away_timeouts
        self.last_play = last_play
        # Rich details
        self.home_record = home_record
        self.away_record = away_record
        self.venue_name = venue_name
        self.venue_city = venue_city
        self.venue_state = venue_state
        self.weather = weather
        self.network = network
        self.odds = odds
        self.win_prob_home = win_prob_home
        self.win_prob_away = win_prob_away
        self.drive_summary = drive_summary

    @property
    def is_live(self) -> bool:
        return self.state == "in"

    @property
    def is_final(self) -> bool:
        return self.state == "post"


def fetch_live_event(event_id: str) -> Optional[LiveGame]:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(ESPN_SUMMARY_URL, params={"event": event_id})
            resp.raise_for_status()
            data = resp.json()
        return _parse_summary(event_id, data)
    except httpx.HTTPStatusError as e:
        try:
            status = e.response.status_code if e.response is not None else None
        except Exception:
            status = None
        # Cache known-bad events for a while to avoid repeated 404 spam
        if status in (404, 410):
            now = time.time()
            _NEG_CACHE[event_id] = now + _NEGATIVE_TTL_SECONDS
            logger.debug("fetch_live_event negative-cache event_id=%s status=%s", event_id, status)
            return None
        logger.debug("fetch_live_event failed: %s", e)
        return None
    except Exception as e:
        logger.debug("fetch_live_event failed: %s", e)
        return None


def bulk_fetch_live_events(event_ids: Iterable[str], force: bool = False) -> Dict[str, LiveGame]:
    """Fetch live summaries for the given ESPN event IDs.

    If force=True, bypasses both positive and negative caches for the specified IDs
    to guarantee a fresh pull (useful for admin backfills after prior 404s).
    """
    out: Dict[str, LiveGame] = {}
    now = time.time()
    to_fetch: List[str] = []
    ids = set(e for e in event_ids if e)

    if force:
        # Clear caches for the requested IDs
        for eid in ids:
            _CACHE.pop(eid, None)
            _NEG_CACHE.pop(eid, None)

    for eid in ids:
        cached = _CACHE.get(eid)
        # Skip known-bad ids until negative cache expires (unless force cleared it)
        neg_expiry = _NEG_CACHE.get(eid)
        if not force and neg_expiry is not None and now <= neg_expiry:
            continue
        if not force and cached and (now - cached[0] <= _CACHE_TTL_SECONDS):
            out[eid] = cached[1]
        else:
            to_fetch.append(eid)
    for eid in to_fetch:
        lg = fetch_live_event(eid)
        if lg:
            out[eid] = lg
            _CACHE[eid] = (now, lg)
    return out


def _parse_summary(event_id: str, data: dict) -> Optional[LiveGame]:
    try:
        header = data.get("header") or {}
        comps = (header.get("competitions") or [])
        if not comps:
            return None
        comp = comps[0]
        status = comp.get("status") or {}
        stype = status.get("type") or {}
        state = (stype.get("state") or "").lower()  # pre | in | post
        display_clock = status.get("displayClock")
        period = status.get("period")
        competitors = comp.get("competitors") or []
        home_score = None
        away_score = None
        home_abbr = None
        away_abbr = None
        home_timeouts = None
        away_timeouts = None
        home_record = None
        away_record = None
        for c in competitors:
            team = c.get("team") or {}
            abbr = (team.get("abbreviation") or "").upper()
            score = None
            try:
                score = int(c.get("score")) if c.get("score") is not None else None
            except Exception:
                score = None
            # record summary like "10-6"
            try:
                recs = c.get("records") or []
                if recs:
                    rec_sum = recs[0].get("summary")
                    if c.get("homeAway") == "home":
                        home_record = rec_sum
                    elif c.get("homeAway") == "away":
                        away_record = rec_sum
            except Exception:
                pass
            if c.get("homeAway") == "home":
                home_score = score
                home_abbr = abbr
                try:
                    home_timeouts = int(c.get("timeouts")) if c.get("timeouts") is not None else None
                except Exception:
                    home_timeouts = None
            elif c.get("homeAway") == "away":
                away_score = score
                away_abbr = abbr
                try:
                    away_timeouts = int(c.get("timeouts")) if c.get("timeouts") is not None else None
                except Exception:
                    away_timeouts = None

        # Situation details
        sit = comp.get("situation") or {}
        down_distance = sit.get("downDistanceText") or sit.get("shortDownDistanceText")
        yard_line = sit.get("yardLine")
        is_red_zone = sit.get("isRedZone")
        possession = None
        poss_val = sit.get("possession")
        if poss_val and isinstance(poss_val, str):
            p = poss_val.upper()
            if home_abbr and p == home_abbr:
                possession = "home"
            elif away_abbr and p == away_abbr:
                possession = "away"
        # Last play text may be in situation or in drives/lastPlay; try situation first
        last_play = sit.get("lastPlayText") or sit.get("lastPlay")

        # Venue & broadcast/network
        venue_name = None
        venue_city = None
        venue_state = None
        try:
            v = comp.get("venue") or {}
            venue_name = v.get("fullName") or v.get("name")
            addr = v.get("address") or {}
            venue_city = addr.get("city")
            venue_state = addr.get("state")
        except Exception:
            pass
        network = None
        try:
            broadcasts = comp.get("broadcasts") or []
            if broadcasts:
                b = broadcasts[0]
                names = b.get("names") or []
                if names:
                    network = ", ".join(n for n in names if isinstance(n, str)) or None
                else:
                    network = b.get("shortName") or b.get("name") or None
        except Exception:
            pass

        # Weather (from gameInfo)
        weather = None
        try:
            gi = data.get("gameInfo") or {}
            w = gi.get("weather") or {}
            # Prefer displayValue if present; otherwise compose temperature + condition
            weather = w.get("displayValue")
            if not weather:
                temp = w.get("temperature")
                unit = w.get("unit") or "F"
                cond = w.get("condition")
                if temp is not None and cond:
                    weather = f"{temp}°{unit} {cond}"
                elif temp is not None:
                    weather = f"{temp}°{unit}"
        except Exception:
            pass

        # Odds (compact text summary)
        odds_text = None
        try:
            # Try competitions[0].odds first
            olist = (comp.get("odds") or [])
            o = olist[0] if olist else None
            if not o:
                # Fall back to top-level pickcenter
                pc = data.get("pickcenter") or []
                o = pc[0] if pc else None
            if o:
                details = o.get("details") or None
                if details and isinstance(details, str):
                    odds_text = details
                else:
                    # Construct simple summary if spread/ou present
                    spread = o.get("spread")
                    ou = o.get("overUnder")
                    prov = (o.get("provider") or {}).get("name")
                    parts: List[str] = []
                    if spread is not None:
                        parts.append(f"Spread {spread}")
                    if ou is not None:
                        parts.append(f"O/U {ou}")
                    if prov:
                        parts.append(f"{prov}")
                    if parts:
                        odds_text = " • ".join(parts)
        except Exception:
            pass

        # Win probability (latest)
        win_prob_home = None
        win_prob_away = None
        try:
            wps = data.get("winprobability") or []
            latest = wps[-1] if isinstance(wps, list) and wps else None
            if latest and isinstance(latest, dict):
                # ESPN often uses homeWinPercentage 0..1
                h = latest.get("homeWinPercentage")
                if isinstance(h, (int, float)):
                    win_prob_home = round(float(h) * 100, 1)
                    win_prob_away = round(100 - win_prob_home, 1)
            if win_prob_home is None:
                # Try predictor
                pred = data.get("predictor") or {}
                home_proj = pred.get("homeTeam", {}).get("gameProjection")
                away_proj = pred.get("awayTeam", {}).get("gameProjection")
                if isinstance(home_proj, (int, float)) and isinstance(away_proj, (int, float)):
                    win_prob_home = round(float(home_proj), 1)
                    win_prob_away = round(float(away_proj), 1)
        except Exception:
            pass

        # Drive summary (current)
        drive_summary = None
        try:
            drives = data.get("drives") or {}
            curr = drives.get("current") or {}
            # Some responses have plays as a list; others have counts
            plays = curr.get("plays")
            if isinstance(plays, list):
                play_count = len(plays)
            else:
                play_count = int(plays) if isinstance(plays, (int, float, str)) else None
            yards = curr.get("yards")
            if yards is None and isinstance(plays, list) and plays:
                # Fallback: sum yards if present
                try:
                    yards = sum(int(p.get("yards", 0)) for p in plays if isinstance(p, dict))
                except Exception:
                    yards = None
            if play_count is not None or yards is not None:
                if play_count is not None and yards is not None:
                    drive_summary = f"{play_count} plays, {yards} yds"
                elif play_count is not None:
                    drive_summary = f"{play_count} plays"
                elif yards is not None:
                    drive_summary = f"{yards} yds"
            # If no last_play from situation, try last play text from drives
            if not last_play and isinstance(plays, list) and plays:
                try:
                    lp = plays[-1]
                    txt = lp.get("text") or lp.get("description")
                    if isinstance(txt, str):
                        last_play = txt
                except Exception:
                    pass
        except Exception:
            pass

        return LiveGame(
            event_id=event_id,
            state=state,
            display_clock=display_clock,
            period=int(period) if isinstance(period, int) else None,
            home_score=home_score,
            away_score=away_score,
            possession=possession,
            down_distance=down_distance,
            yard_line=str(yard_line) if yard_line is not None else None,
            is_red_zone=bool(is_red_zone) if is_red_zone is not None else None,
            home_timeouts=home_timeouts,
            away_timeouts=away_timeouts,
            last_play=last_play if isinstance(last_play, str) else None,
            home_record=home_record,
            away_record=away_record,
            venue_name=venue_name,
            venue_city=venue_city,
            venue_state=venue_state,
            weather=weather,
            network=network,
            odds=odds_text,
            win_prob_home=win_prob_home,
            win_prob_away=win_prob_away,
            drive_summary=drive_summary,
        )
    except Exception as e:
        logger.debug("_parse_summary failed: %s", e)
        return None
