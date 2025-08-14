from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.templates import templates, default_avatar
from app.db.session import get_db
from app.deps.auth import get_current_user
from app.models import Week, Game, GameStatus, Pick, User, Season, TieBreaker
from app.services.nfl.live import bulk_fetch_live_events
from app.services.nfl.live import LiveGame

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, week: Optional[int] = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    try:
        # Determine selected week (query param or current)
        selected_week: Optional[Week] = None
        if week is not None:
            selected_week = db.query(Week).filter(Week.id == week).first()
        if not selected_week:
            selected_week = _get_current_week(db)

        # Build weeks list for selector (entire season across all segments)
        weeks = (
            db.query(Week)
            .filter(Week.season_id == selected_week.season_id)
            .order_by(Week.season_type, Week.week_number)
            .all()
            if selected_week
            else []
        )

        # Prev/Next helpers
        prev_week: Optional[Week] = None
        next_week: Optional[Week] = None
        if selected_week and weeks:
            try:
                idx = [w.id for w in weeks].index(selected_week.id)
                if idx > 0:
                    prev_week = weeks[idx - 1]
                if idx < len(weeks) - 1:
                    next_week = weeks[idx + 1]
            except ValueError:
                pass

        # User picks progress for this week
        total_games = 0
        picks_made = 0
        missing = 0
        needs_picks = False
        if selected_week:
            games = db.query(Game).filter(Game.week_id == selected_week.id).all()
            total_games = len(games)
            game_ids = [g.id for g in games]
            if game_ids:
                picks_made = (
                    db.query(Pick.id)
                    .filter(Pick.user_id == user.id, Pick.game_id.in_(game_ids))
                    .count()
                )
            missing = max(0, total_games - picks_made)
            needs_picks = (missing > 0) and (not selected_week.is_locked())

        # Simple season leaderboard (based on FINAL games only)
        leaderboard, decided_games_count = _season_leaderboard(db, selected_week)

        # Weekly lunch outcome (winner/loser)
        lunch = _weekly_lunch(db, selected_week)

        logger.debug(
            "Dashboard context built",
            extra={
                "user_id": user.id,
                "selected_week_id": getattr(selected_week, "id", None),
                "picks_made": picks_made,
                "total_games": total_games,
                "missing": missing,
                "decided_games_count": decided_games_count,
            },
        )

        context = {
            "request": request,
            "title": "Dashboard",
            "current_user": user,
            "selected_week": selected_week,
            "weeks": weeks,
            "prev_week": prev_week,
            "next_week": next_week,
            "needs_picks": needs_picks,
            "picks_made": picks_made,
            "total_games": total_games,
            "missing": missing,
            "leaderboard": leaderboard,
            "decided_games_count": decided_games_count,
            "lunch": lunch,
        }
        return templates.TemplateResponse("dashboard.html", context)
    except Exception:
        logger.exception("Error rendering dashboard")
        safe_ctx = {
            "request": request,
            "title": "Dashboard",
            "current_user": user,
            "selected_week": None,
            "weeks": [],
            "prev_week": None,
            "next_week": None,
            "needs_picks": False,
            "picks_made": 0,
            "total_games": 0,
            "missing": 0,
            "leaderboard": [],
            "decided_games_count": 0,
        }
        return templates.TemplateResponse("dashboard.html", safe_ctx)


def _get_current_week(db: Session) -> Optional[Week]:
    now = datetime.now(timezone.utc)
    upcoming = (
        db.query(Week).filter(Week.first_kickoff_at >= now).order_by(Week.first_kickoff_at.asc()).first()
    )
    if upcoming:
        return upcoming
    return db.query(Week).order_by(Week.first_kickoff_at.desc()).first()


def _active_season(db: Session, selected_week: Optional[Week]) -> Optional[Season]:
    if selected_week:
        return db.query(Season).filter(Season.id == selected_week.season_id).first()
    active = db.query(Season).filter(Season.is_active == True).order_by(Season.year.desc()).first()  # noqa: E712
    if active:
        return active
    return db.query(Season).order_by(Season.year.desc()).first()


def _season_leaderboard(db: Session, selected_week: Optional[Week]):
    season = _active_season(db, selected_week)
    if not season:
        return [], 0

    # Consider only FINAL games with a decided winner (no ties)
    final_games: List[Game] = (
        db.query(Game)
        .filter(Game.season_id == season.id, Game.status == GameStatus.FINAL)
        .all()
    )
    winners_by_game: Dict[int, Optional[int]] = {}
    for g in final_games:
        if g.home_score > g.away_score:
            winners_by_game[g.id] = g.home_team_id
        elif g.away_score > g.home_score:
            winners_by_game[g.id] = g.away_team_id
        else:
            winners_by_game[g.id] = None  # tie

    decided_game_ids = [gid for gid, winner in winners_by_game.items() if winner is not None]
    if not decided_game_ids:
        return [], 0

    picks: List[Pick] = db.query(Pick).filter(Pick.game_id.in_(decided_game_ids)).all()
    # Map user -> counts
    correct_counts: Dict[int, int] = {}
    pick_counts: Dict[int, int] = {}
    for p in picks:
        winner = winners_by_game.get(p.game_id)
        if winner is None:
            continue
        pick_counts[p.user_id] = pick_counts.get(p.user_id, 0) + 1
        if p.chosen_team_id == winner:
            correct_counts[p.user_id] = correct_counts.get(p.user_id, 0) + 1

    if not pick_counts:
        return [], len(decided_game_ids)

    user_ids = list(pick_counts.keys())
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    name_by_id = {u.id: (u.display_name or u.username) for u in users}
    user_by_id = {u.id: u for u in users}

    board = []
    for uid in user_ids:
        corr = correct_counts.get(uid, 0)
        total = pick_counts.get(uid, 0)
        pct = (corr / total) if total else 0.0
        board.append({
            "user_id": uid,
            "name": name_by_id.get(uid, f"User {uid}"),
            "correct": corr,
            "picks": total,
            "pct": pct,
        })

    board.sort(key=lambda x: (-x["correct"], -x["pct"], x["name"].lower()))
    return board[:10], len(decided_game_ids)


def _weekly_lunch(db: Session, week: Optional[Week]):
    """
    Compute lunch winner/loser for a week.

    Winner: highest correct picks; if tie and week finalized, closest tiebreaker guess
    to the actual Monday total points (approx as the last game of the week) without
    going over.
    Loser: lowest correct picks (ties allowed).
    """
    if not week:
        return {"status": "no_week"}

    games: List[Game] = db.query(Game).filter(Game.week_id == week.id).all()
    total_games = len(games)
    if total_games == 0:
        return {"status": "no_games", "total_games": 0, "decided_games": 0}

    final_games: List[Game] = [g for g in games if g.status == GameStatus.FINAL]
    decided_games = len(final_games)
    week_finalized = decided_games == total_games

    # Winners by game for decided (non-tie) finals
    winners_by_game: Dict[int, Optional[int]] = {}
    for g in final_games:
        if g.home_score > g.away_score:
            winners_by_game[g.id] = g.home_team_id
        elif g.away_score > g.home_score:
            winners_by_game[g.id] = g.away_team_id
        else:
            winners_by_game[g.id] = None

    decided_ids = [gid for gid, w in winners_by_game.items() if w is not None]
    weekly_picks: List[Pick] = []
    if decided_ids:
        weekly_picks = db.query(Pick).filter(Pick.game_id.in_(decided_ids)).all()

    # Aggregate per-user
    correct_counts: Dict[int, int] = {}
    pick_counts: Dict[int, int] = {}
    for p in weekly_picks:
        winner = winners_by_game.get(p.game_id)
        if winner is None:
            continue
        pick_counts[p.user_id] = pick_counts.get(p.user_id, 0) + 1
        if p.chosen_team_id == winner:
            correct_counts[p.user_id] = correct_counts.get(p.user_id, 0) + 1

    if not pick_counts:
        return {
            "status": "pending",
            "total_games": total_games,
            "decided_games": decided_games,
        }

    user_ids = list(pick_counts.keys())
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    name_by_id = {u.id: (u.display_name or u.username) for u in users}
    user_by_id = {u.id: u for u in users}

    # Tiebreakers for this week
    tbs: List[TieBreaker] = db.query(TieBreaker).filter(TieBreaker.week_id == week.id, TieBreaker.user_id.in_(user_ids)).all()
    tb_by_user: Dict[int, int] = {t.user_id: t.guess_points for t in tbs}

    # Actual tiebreaker total: use last FINAL game total as approximation of Monday total
    actual_total: Optional[int] = None
    if week_finalized and final_games:
        def _aware_utc(dt: datetime) -> datetime:
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        last_game = max(final_games, key=lambda g: _aware_utc(g.start_time))
        actual_total = (last_game.home_score or 0) + (last_game.away_score or 0)

    # Build rows
    rows = []
    for uid in user_ids:
        corr = correct_counts.get(uid, 0)
        tot = pick_counts.get(uid, 0)
        rows.append({
            "user_id": uid,
            "name": name_by_id.get(uid, f"User {uid}"),
            "correct": corr,
            "picks": tot,
            "pct": (corr / tot) if tot else 0.0,
            "tb": tb_by_user.get(uid),
        })

    # Determine winner(s) and loser(s)
    participants = len(rows)
    max_correct = max(r["correct"] for r in rows) if rows else 0
    min_correct = min(r["correct"] for r in rows) if rows else 0
    winners = [r for r in rows if r["correct"] == max_correct]
    losers = [r for r in rows if r["correct"] == min_correct] if participants > 1 else []
    winner_uids = [w["user_id"] for w in winners]
    loser_uids = [l["user_id"] for l in losers]

    winner_names: List[str] = [w["name"] for w in winners]
    tb_applied = False
    if week_finalized and len(winners) > 1 and actual_total is not None:
        # Apply closest without going over
        eligible = [w for w in winners if w.get("tb") is not None and w["tb"] <= actual_total]
        if eligible:
            tb_applied = True
            best = max(eligible, key=lambda w: w["tb"])  # unique by constraint
            winner_names = [best["name"]]
            winner_uids = [best["user_id"]]

    # Break ties for loser using tiebreaker when possible
    loser_tb_applied = False
    if week_finalized and len(losers) > 1 and actual_total is not None:
        # Ranking:
        #  - Over guesses are worse than under/equal guesses (closest without going over wins)
        #  - Within category, farther from actual total is worse
        #  - Missing tiebreaker is worst
        def _loss_key(r):
            tb = r.get("tb")
            if tb is None:
                return (3, float("inf"))
            if tb <= actual_total:
                return (1, actual_total - tb)
            else:
                return (2, tb - actual_total)

        worst = max(losers, key=_loss_key)
        loser_names: List[str] = [worst["name"]]
        loser_uids = [worst["user_id"]]
        loser_tb_applied = True
    else:
        loser_names: List[str] = [l["name"] for l in losers]

    # Build DTOs with avatar URLs
    def _user_dto(uid: int):
        u = user_by_id.get(uid)
        name = name_by_id.get(uid, f"User {uid}")
        raw = getattr(u, "avatar_path", None) if u else None
        avatar_url = raw or (default_avatar(u) if u else None)
        return {"user_id": uid, "name": name, "avatar_url": avatar_url}

    winner_users = [_user_dto(uid) for uid in winner_uids]
    loser_users = [_user_dto(uid) for uid in loser_uids]

    status = "decided" if week_finalized and (len(winner_names) > 0) else "pending"
    return {
        "status": status,
        "total_games": total_games,
        "decided_games": decided_games,
        "winner_names": winner_names,
        "loser_names": loser_names,
        "winner_users": winner_users,
        "loser_users": loser_users,
        "actual_total": actual_total,
        "tiebreaker_applied": tb_applied,
        "loser_tiebreaker_applied": loser_tb_applied,
    }


@router.get("/dashboard/content", response_class=HTMLResponse)
def dashboard_content(request: Request, week: Optional[int] = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    try:
        # Determine selected week
        selected_week: Optional[Week] = None
        if week is not None:
            selected_week = db.query(Week).filter(Week.id == week).first()
        if not selected_week:
            selected_week = _get_current_week(db)

        # Build weeks list for selector (same season and season_type as selected week)
        weeks = (
            db.query(Week)
            .filter(
                Week.season_id == selected_week.season_id,
                Week.season_type == selected_week.season_type,
            )
            .order_by(Week.week_number)
            .all()
            if selected_week
            else []
        )

        # Prev/Next helpers
        prev_week: Optional[Week] = None
        next_week: Optional[Week] = None
        if selected_week and weeks:
            try:
                idx = [w.id for w in weeks].index(selected_week.id)
                if idx > 0:
                    prev_week = weeks[idx - 1]
                if idx < len(weeks) - 1:
                    next_week = weeks[idx + 1]
            except ValueError:
                pass

        # User picks progress
        total_games = 0
        picks_made = 0
        missing = 0
        needs_picks = False
        if selected_week:
            games = db.query(Game).filter(Game.week_id == selected_week.id).all()
            total_games = len(games)
            game_ids = [g.id for g in games]
            if game_ids:
                picks_made = (
                    db.query(Pick.id)
                    .filter(Pick.user_id == user.id, Pick.game_id.in_(game_ids))
                    .count()
                )
            missing = max(0, total_games - picks_made)
            needs_picks = (missing > 0) and (not selected_week.is_locked())

        # Leaderboard and lunch
        leaderboard, decided_games_count = _season_leaderboard(db, selected_week)
        lunch = _weekly_lunch(db, selected_week)

        context = {
            "request": request,
            "title": "Dashboard",
            "current_user": user,
            "selected_week": selected_week,
            "weeks": weeks,
            "prev_week": prev_week,
            "next_week": next_week,
            "needs_picks": needs_picks,
            "picks_made": picks_made,
            "total_games": total_games,
            "missing": missing,
            "leaderboard": leaderboard,
            "decided_games_count": decided_games_count,
            "lunch": lunch,
        }
        push_url = f"/dashboard?week={selected_week.id}" if selected_week else "/dashboard"
        return templates.TemplateResponse("dashboard_content.html", context, headers={"HX-Push-Url": push_url})
    except Exception:
        logger.exception("Error rendering dashboard content")
        safe_ctx = {
            "request": request,
            "title": "Dashboard",
            "current_user": user,
            "selected_week": None,
            "weeks": [],
            "prev_week": None,
            "next_week": None,
            "needs_picks": False,
            "picks_made": 0,
            "total_games": 0,
            "missing": 0,
            "leaderboard": [],
            "decided_games_count": 0,
            "lunch": None,
        }
        return templates.TemplateResponse("dashboard_content.html", safe_ctx, headers={"HX-Push-Url": "/dashboard"})

@router.get("/dashboard/live", response_class=HTMLResponse)
def dashboard_live(request: Request, week: Optional[int] = None, demo: Optional[int] = None, db: Session = Depends(get_db)):
    """HTMX fragment: live games grid with logos, scores, status/clock, and who-picked-who.

    Returns a section div with id="live-board" so the client can hx-swap outerHTML.
    """
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    # Resolve selected week from query param or fall back to current
    selected_week: Optional[Week] = None
    if week is not None:
        selected_week = db.query(Week).filter(Week.id == week).first()
    if not selected_week:
        selected_week = _get_current_week(db)
    games: List[Game] = (
        db.query(Game).filter(Game.week_id == selected_week.id).order_by(Game.start_time).all()
        if selected_week
        else []
    )

    # Teams lookup
    team_ids = set()
    for g in games:
        team_ids.add(g.home_team_id)
        team_ids.add(g.away_team_id)
    teams_by_id: Dict[int, "Team"] = {}
    if team_ids:
        from app.models.team import Team  # local import to avoid cycles
        for t in db.query(Team).filter(Team.id.in_(list(team_ids))).all():
            teams_by_id[t.id] = t

    game_ids = [g.id for g in games]

    # Current user's picks this week to highlight selection
    user_picks: Dict[int, int] = {}
    if game_ids:
        rows = db.query(Pick).filter(Pick.user_id == user.id, Pick.game_id.in_(game_ids)).all()
        user_picks = {p.game_id: p.chosen_team_id for p in rows}

    # Who picked who (counts + sample names up to 6 per side) + avatar info per side
    picks_summary: Dict[int, Dict[str, object]] = {}
    if game_ids:
        all_picks: List[Pick] = db.query(Pick).filter(Pick.game_id.in_(game_ids)).all()
        # Collect user ids for name lookup
        uids = {p.user_id for p in all_picks}
        users = db.query(User).filter(User.id.in_(list(uids))).all() if uids else []
        name_by_id = {u.id: (u.display_name or u.username) for u in users}
        avatar_by_id = {u.id: (u.avatar_path or None) for u in users}
        user_by_id = {u.id: u for u in users}
        by_game: Dict[int, Dict[str, object]] = {}
        for g in games:
            by_game[g.id] = {
                "home_count": 0,
                "away_count": 0,
                "home_names": [],  # sample up to 6
                "away_names": [],  # sample up to 6
                "home_all": [],
                "away_all": [],
                "home_users": [],  # list of {name, avatar_url}
                "away_users": [],
            }
        for p in all_picks:
            gmap = by_game.get(p.game_id)
            if not gmap:
                continue
            name = name_by_id.get(p.user_id, f"User {p.user_id}")
            raw_avatar = avatar_by_id.get(p.user_id)
            u_model = user_by_id.get(p.user_id)
            avatar_url = raw_avatar or (default_avatar(u_model) if u_model else None)
            # determine side
            g = next((x for x in games if x.id == p.game_id), None)
            if not g:
                continue
            if p.chosen_team_id == g.home_team_id:
                gmap["home_count"] = int(gmap.get("home_count", 0)) + 1
                gmap["home_all"].append(name)
                if len(gmap["home_names"]) < 6:
                    gmap["home_names"].append(name)
                gmap["home_users"].append({"name": name, "avatar_url": avatar_url})
            elif p.chosen_team_id == g.away_team_id:
                gmap["away_count"] = int(gmap.get("away_count", 0)) + 1
                gmap["away_all"].append(name)
                if len(gmap["away_names"]) < 6:
                    gmap["away_names"].append(name)
                gmap["away_users"].append({"name": name, "avatar_url": avatar_url})
        picks_summary = by_game

    # Live clocks from ESPN for non-final games with a provider id
    event_ids = [g.provider_game_id for g in games if g.provider_game_id and g.status != GameStatus.FINAL]
    live_map = bulk_fetch_live_events(event_ids) if event_ids else {}

    # Group games by status for UI sections
    live_games: List[Game] = []
    upcoming_games: List[Game] = []
    final_games: List[Game] = []
    for g in games:
        lg = live_map.get(g.provider_game_id) if g.provider_game_id else None
        if g.status == GameStatus.FINAL or (lg and lg.is_final):
            final_games.append(g)
        elif lg and lg.is_live:
            live_games.append(g)
        else:
            upcoming_games.append(g)

    # Adaptive refresh: faster when any game is live
    refresh_interval = 15 if live_games else 60

    # Optional demo preview card context
    demo_mode = bool(demo)
    demo_home = None
    demo_away = None
    demo_live = None
    if demo_mode:
        try:
            # Prefer first game teams if available for accurate logos
            base_home_id = games[0].home_team_id if games else None
            base_away_id = games[0].away_team_id if games else None
            if (not base_home_id or not base_away_id) and not teams_by_id:
                from app.models.team import Team  # local import to avoid cycles
                any_two = db.query(Team).limit(2).all()
                if len(any_two) >= 2:
                    teams_by_id[any_two[0].id] = any_two[0]
                    teams_by_id[any_two[1].id] = any_two[1]
                    base_home_id = any_two[0].id
                    base_away_id = any_two[1].id
            demo_home = teams_by_id.get(base_home_id) if base_home_id else None
            demo_away = teams_by_id.get(base_away_id) if base_away_id else None
            # Construct a realistic demo LiveGame
            demo_live = LiveGame(
                event_id="demo",
                state="in",
                display_clock="07:21",
                period=2,
                home_score=14,
                away_score=17,
                possession="home",
                down_distance="3rd & 7",
                yard_line="OWN 42",
                is_red_zone=False,
                home_timeouts=2,
                away_timeouts=3,
                last_play="QB pass short left complete for 9 yards",
                home_record="10-4",
                away_record="8-6",
                venue_name="Demo Stadium",
                venue_city="Metropolis",
                venue_state="NY",
                weather="68°F Clear",
                network="ESPN",
                odds="HOME -2.5 • O/U 45.5",
                win_prob_home=55.3,
                win_prob_away=44.7,
                drive_summary="6 plays, 34 yds",
            )
        except Exception:
            logger.debug("Failed to build demo live preview", exc_info=True)

    ctx = {
        "request": request,
        "games": games,
        "teams_by_id": teams_by_id,
        "user_picks": user_picks,
        "picks_summary": picks_summary,
        "live_map": live_map,
        "selected_week": selected_week,
        "live_games": live_games,
        "upcoming_games": upcoming_games,
        "final_games": final_games,
        "refresh_interval": refresh_interval,
        "demo_mode": demo_mode,
        "demo_home": demo_home,
        "demo_away": demo_away,
        "demo_live": demo_live,
    }
    return templates.TemplateResponse("dashboard_live.html", ctx)
