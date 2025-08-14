from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Iterable, Tuple

from sqlalchemy.orm import Session

from app.models import Team, Season, Week, Game, GameStatus
from .base import NFLProvider, ProviderTeam, ProviderGame


def _team_lookup_map(db: Session) -> Dict[str, Team]:
    """Return a mapping from abbr/alt_abbr to Team."""
    out: Dict[str, Team] = {}
    teams = db.query(Team).all()
    for t in teams:
        if t.abbr:
            out[t.abbr.upper()] = t
        for alt in t.alt_abbreviations():
            out[alt.upper()] = t
    return out


def upsert_teams_from_provider(db: Session, provider: NFLProvider) -> Tuple[int, int]:
    """Insert or update teams from provider. Returns (inserted, updated)."""
    inserted = 0
    updated = 0
    existing_by_abbr: Dict[str, Team] = {t.abbr.upper(): t for t in db.query(Team).all()}

    for pt in provider.get_teams():
        abbr = pt.abbr.upper()
        t = existing_by_abbr.get(abbr)
        alt_json = json.dumps(pt.alt_abbrs or [])
        if t is None:
            t = Team(
                slug=(pt.slug or abbr.lower()),
                name=pt.name,
                location=pt.location,
                abbr=abbr,
                alt_abbrs=alt_json,
                logo_path=pt.logo_path,
            )
            db.add(t)
            inserted += 1
        else:
            changed = False
            if t.name != pt.name:
                t.name = pt.name
                changed = True
            if t.location != pt.location:
                t.location = pt.location
                changed = True
            if t.slug != (pt.slug or abbr.lower()):
                t.slug = (pt.slug or abbr.lower())
                changed = True
            # Only update alt abbreviations if provider explicitly supplies them
            if pt.alt_abbrs is not None:
                if (t.alt_abbrs or "[]") != alt_json:
                    t.alt_abbrs = alt_json
                    changed = True
            if pt.logo_path and t.logo_path != pt.logo_path:
                t.logo_path = pt.logo_path
                changed = True
            if changed:
                db.add(t)
                updated += 1

    db.commit()
    return inserted, updated


def refresh_team_logos(db: Session, provider: NFLProvider) -> Tuple[int, int]:
    """Update only Team.logo_path values based on the provider's latest data.

    Returns (updated, skipped) counts.
    """
    updated = 0
    skipped = 0
    by_abbr: Dict[str, Team] = {t.abbr.upper(): t for t in db.query(Team).all()}
    provider_teams = list(provider.get_teams())
    for pt in provider_teams:
        abbr = pt.abbr.upper()
        t = by_abbr.get(abbr)
        if not t:
            skipped += 1
            continue
        if not pt.logo_path:
            skipped += 1
            continue
        if t.logo_path != pt.logo_path:
            t.logo_path = pt.logo_path
            db.add(t)
            updated += 1
        else:
            skipped += 1
    db.commit()
    return updated, skipped


def import_week_schedule(db: Session, provider: NFLProvider, season_year: int, week_number: int, season_type: int = 2) -> int:
    """Import or upsert games for a given season/week. Returns number of games upserted.

    Assumes teams are already present.
    """
    season = db.query(Season).filter(Season.year == season_year).first()
    if not season:
        season = Season(year=season_year, is_active=True)
        db.add(season)
        db.flush()

    week = (
        db.query(Week)
        .filter(
            Week.season_id == season.id,
            Week.week_number == week_number,
            Week.season_type == season_type,
        )
        .first()
    )
    if not week:
        week = Week(
            season_id=season.id,
            week_number=week_number,
            season_type=season_type,
            first_kickoff_at=datetime.now(timezone.utc),
        )
        db.add(week)
        db.flush()

    lookup = _team_lookup_map(db)

    upserted = 0
    games = list(provider.get_week_schedule(season_year, week_number, season_type=season_type))
    if not games:
        # nothing to import (local provider)
        return 0

    start_times = []
    for pg in games:
        home = lookup.get(pg.home_abbr.upper())
        away = lookup.get(pg.away_abbr.upper())
        if not home or not away:
            # skip if teams missing
            continue

        # Try to find existing game by provider_game_id, else by home/away/time exact
        g = None
        if pg.provider_game_id:
            g = db.query(Game).filter(Game.week_id == week.id, Game.provider_game_id == pg.provider_game_id).first()
        if g is None:
            g = (
                db.query(Game)
                .filter(
                    Game.week_id == week.id,
                    Game.home_team_id == home.id,
                    Game.away_team_id == away.id,
                    Game.start_time == pg.start_time,
                )
                .first()
            )
        if g is None:
            g = Game(
                season_id=season.id,
                week_id=week.id,
                home_team_id=home.id,
                away_team_id=away.id,
                start_time=pg.start_time,
                status=GameStatus.SCHEDULED,
                provider_game_id=pg.provider_game_id,
            )
            db.add(g)
            upserted += 1
        else:
            changed = False
            if g.start_time != pg.start_time:
                g.start_time = pg.start_time
                changed = True
            if g.home_team_id != home.id or g.away_team_id != away.id:
                g.home_team_id = home.id
                g.away_team_id = away.id
                changed = True
            if pg.provider_game_id and g.provider_game_id != pg.provider_game_id:
                g.provider_game_id = pg.provider_game_id
                changed = True
            if changed:
                db.add(g)
                upserted += 1

        start_times.append(pg.start_time)

    # Update first_kickoff_at to earliest start time if we imported any
    if start_times:
        week.first_kickoff_at = min(start_times)
        db.add(week)

    db.commit()
    return upserted


def import_full_season(
    db: Session,
    provider: NFLProvider,
    season_year: int,
    include_preseason: bool = True,
    include_postseason: bool = True,
) -> Dict[str, int]:
    """Import an entire season across preseason, regular, and postseason.

    Returns a summary dict with counts, e.g. {"pre": x, "reg": y, "post": z, "total": t, "weeks": w}.
    """
    summary: Dict[str, int] = {"pre": 0, "reg": 0, "post": 0, "total": 0, "weeks": 0}

    # Preseason: typically 1-3 or 1-4 depending on year; try up to 4
    if include_preseason:
        for wk in range(1, 5):
            c = import_week_schedule(db, provider, season_year, wk, season_type=1)
            if c > 0:
                summary["pre"] += c
                summary["weeks"] += 1

    # Regular: 1-18 since 2021
    for wk in range(1, 19):
        c = import_week_schedule(db, provider, season_year, wk, season_type=2)
        if c > 0:
            summary["reg"] += c
            summary["weeks"] += 1

    # Postseason: try up to 5 (WC, DIV, CONF, PB?, SB). PB may be absent; safe to try.
    if include_postseason:
        for wk in range(1, 6):
            c = import_week_schedule(db, provider, season_year, wk, season_type=3)
            if c > 0:
                summary["post"] += c
                summary["weeks"] += 1

    summary["total"] = summary["pre"] + summary["reg"] + summary["post"]
    return summary
