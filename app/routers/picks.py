from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional
import logging

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.templates import templates
from app.db.session import get_db
from app.deps.auth import get_current_user
from app.models.week import Week
from app.models.game import Game
from app.models.pick import Pick
from app.models.tiebreaker import TieBreaker
from app.models.team import Team
from app.models.season import Season

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/picks", response_class=HTMLResponse)
def picks_page(request: Request, week: Optional[int] = None, db: Session = Depends(get_db)):
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

        # Build list of weeks for selector (entire season across all segments)
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

        games = (
            db.query(Game).filter(Game.week_id == selected_week.id).order_by(Game.start_time).all()
            if selected_week
            else []
        )

        game_ids = [g.id for g in games]
        existing_picks: Dict[int, int] = {}
        if game_ids:
            rows = (
                db.query(Pick).filter(Pick.user_id == user.id, Pick.game_id.in_(game_ids)).all()
            )
            existing_picks = {p.game_id: p.chosen_team_id for p in rows}

        # Teams lookup for rendering
        team_ids = set()
        for g in games:
            team_ids.add(g.home_team_id)
            team_ids.add(g.away_team_id)
        teams_by_id: Dict[int, Team] = {}
        if team_ids:
            for t in db.query(Team).filter(Team.id.in_(list(team_ids))).all():
                teams_by_id[t.id] = t

        # Tiebreaker for the user for this week
        tb_guess: Optional[int] = None
        if selected_week:
            tb = (
                db.query(TieBreaker)
                .filter(TieBreaker.user_id == user.id, TieBreaker.week_id == selected_week.id)
                .first()
            )
            if tb:
                tb_guess = tb.guess_points

        locked = selected_week.is_locked() if selected_week else True
        err = request.query_params.get("err")
        ok = request.query_params.get("ok")

        ctx = {
            "request": request,
            "title": "Your Picks",
            "current_user": user,
            "weeks": weeks,
            "selected_week": selected_week,
            "games": games,
            "teams_by_id": teams_by_id,
            "existing_picks": existing_picks,
            "tb_guess": tb_guess,
            "locked": locked,
            "err": err,
            "ok": ok,
            "prev_week": prev_week,
            "next_week": next_week,
        }
        logger.debug(
            "Picks context built",
            extra={
                "user_id": user.id,
                "selected_week_id": getattr(selected_week, "id", None),
                "games": len(games),
                "weeks": len(weeks),
                "have_tb": tb_guess is not None,
                "locked": locked,
            },
        )
        return templates.TemplateResponse("picks.html", ctx)
    except Exception:
        logger.exception("Error rendering picks page")
        safe_ctx = {
            "request": request,
            "title": "Your Picks",
            "current_user": user,
            "weeks": [],
            "selected_week": None,
            "games": [],
            "teams_by_id": {},
            "existing_picks": {},
            "tb_guess": None,
            "locked": True,
            "err": request.query_params.get("err"),
            "ok": request.query_params.get("ok"),
            "prev_week": None,
            "next_week": None,
        }
        return templates.TemplateResponse("picks.html", safe_ctx)


@router.get("/picks/content", response_class=HTMLResponse)
def picks_content(request: Request, week: Optional[int] = None, db: Session = Depends(get_db)):
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

        # Weeks and prev/next (entire season across all segments)
        weeks = (
            db.query(Week)
            .filter(Week.season_id == selected_week.season_id)
            .order_by(Week.season_type, Week.week_number)
            .all()
            if selected_week
            else []
        )

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

        games = (
            db.query(Game).filter(Game.week_id == selected_week.id).order_by(Game.start_time).all()
            if selected_week
            else []
        )

        game_ids = [g.id for g in games]
        existing_picks: Dict[int, int] = {}
        if game_ids:
            rows = (
                db.query(Pick).filter(Pick.user_id == user.id, Pick.game_id.in_(game_ids)).all()
            )
            existing_picks = {p.game_id: p.chosen_team_id for p in rows}

        team_ids = set()
        for g in games:
            team_ids.add(g.home_team_id)
            team_ids.add(g.away_team_id)
        teams_by_id: Dict[int, Team] = {}
        if team_ids:
            for t in db.query(Team).filter(Team.id.in_(list(team_ids))).all():
                teams_by_id[t.id] = t

        tb_guess: Optional[int] = None
        if selected_week:
            tb = (
                db.query(TieBreaker)
                .filter(TieBreaker.user_id == user.id, TieBreaker.week_id == selected_week.id)
                .first()
            )
            if tb:
                tb_guess = tb.guess_points

        locked = selected_week.is_locked() if selected_week else True
        err = request.query_params.get("err")
        ok = request.query_params.get("ok")

        ctx = {
            "request": request,
            "title": "Your Picks",
            "current_user": user,
            "weeks": weeks,
            "selected_week": selected_week,
            "games": games,
            "teams_by_id": teams_by_id,
            "existing_picks": existing_picks,
            "tb_guess": tb_guess,
            "locked": locked,
            "err": err,
            "ok": ok,
            "prev_week": prev_week,
            "next_week": next_week,
        }
        push_url = f"/picks?week={selected_week.id}" if selected_week else "/picks"
        return templates.TemplateResponse("picks_content.html", ctx, headers={"HX-Push-Url": push_url})
    except Exception:
        logger.exception("Error rendering picks content")
        safe_ctx = {
            "request": request,
            "title": "Your Picks",
            "current_user": user,
            "weeks": [],
            "selected_week": None,
            "games": [],
            "teams_by_id": {},
            "existing_picks": {},
            "tb_guess": None,
            "locked": True,
            "err": request.query_params.get("err"),
            "ok": request.query_params.get("ok"),
            "prev_week": None,
            "next_week": None,
        }
        return templates.TemplateResponse("picks_content.html", safe_ctx, headers={"HX-Push-Url": "/picks"})


def _get_current_week(db: Session) -> Optional[Week]:
    now = datetime.now(timezone.utc)
    # Prefer the active season's upcoming (or last) week to avoid cross-season jumps
    season = (
        db.query(Season)
        .filter(Season.is_active == True)  # noqa: E712
        .order_by(Season.year.desc())
        .first()
    )
    if not season:
        season = db.query(Season).order_by(Season.year.desc()).first()
    if season:
        upcoming = (
            db.query(Week)
            .filter(Week.season_id == season.id, Week.first_kickoff_at >= now)
            .order_by(Week.first_kickoff_at.asc())
            .first()
        )
        if upcoming:
            return upcoming
        last_in_season = (
            db.query(Week)
            .filter(Week.season_id == season.id)
            .order_by(Week.first_kickoff_at.desc())
            .first()
        )
        if last_in_season:
            return last_in_season

    # Global fallback: next upcoming week across all seasons, then most recent overall
    upcoming_any = (
        db.query(Week)
        .filter(Week.first_kickoff_at >= now)
        .order_by(Week.first_kickoff_at.asc())
        .first()
    )
    if upcoming_any:
        return upcoming_any
    return db.query(Week).order_by(Week.first_kickoff_at.desc()).first()


@router.post("/picks/save")
async def picks_save(
    request: Request,
    week_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    week = db.query(Week).filter(Week.id == week_id).first()
    if not week:
        return RedirectResponse("/picks?err=noweek", status_code=302)
    if week.is_locked():
        return RedirectResponse(f"/picks?week={week.id}&err=locked", status_code=302)

    form = await request.form()

    # Collect selected picks from form
    picks_posted: Dict[int, int] = {}
    game_ids: list[int] = []
    for key, value in form.items():
        if key.startswith("pick_"):
            try:
                gid = int(key.split("_", 1)[1])
                tid = int(value)
            except Exception:
                continue
            picks_posted[gid] = tid
            game_ids.append(gid)

    # Validate games belong to the week and team IDs valid
    games = db.query(Game).filter(Game.id.in_(game_ids), Game.week_id == week.id).all() if game_ids else []
    valid_game_ids = {g.id for g in games}
    for gid, _ in list(picks_posted.items()):
        if gid not in valid_game_ids:
            picks_posted.pop(gid, None)

    # Upsert picks
    if picks_posted:
        existing = (
            db.query(Pick)
            .filter(Pick.user_id == user.id, Pick.game_id.in_(list(picks_posted.keys())))
            .all()
        )
        by_gid = {p.game_id: p for p in existing}
        for g in games:
            if g.id not in picks_posted:
                continue
            chosen_team_id = picks_posted[g.id]
            # Ensure chosen team is one of the two
            if chosen_team_id not in (g.home_team_id, g.away_team_id):
                continue
            row = by_gid.get(g.id)
            if row:
                row.chosen_team_id = chosen_team_id
            else:
                db.add(Pick(user_id=user.id, game_id=g.id, chosen_team_id=chosen_team_id))

    # Handle tiebreaker
    tb_val_raw = form.get("tiebreaker")
    if tb_val_raw is not None and str(tb_val_raw).strip() != "":
        try:
            tb_val = int(str(tb_val_raw).strip())
            if tb_val < 0:
                return RedirectResponse(f"/picks?week={week.id}&err=tb_invalid", status_code=302)
        except Exception:
            return RedirectResponse(f"/picks?week={week.id}&err=tb_invalid", status_code=302)

        existing_tb = (
            db.query(TieBreaker).filter(TieBreaker.user_id == user.id, TieBreaker.week_id == week.id).first()
        )
        if existing_tb:
            existing_tb.guess_points = tb_val
        else:
            db.add(TieBreaker(user_id=user.id, week_id=week.id, guess_points=tb_val))

    try:
        logger.debug(
            "Saving picks",
            extra={
                "user_id": user.id,
                "week_id": week.id,
                "picks_count": len(picks_posted),
                "has_tb": "tiebreaker" in form,
            },
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.warning("Tiebreaker uniqueness violation", extra={"user_id": user.id, "week_id": week.id})
        # Likely tiebreaker uniqueness violation
        return RedirectResponse(f"/picks?week={week.id}&err=tb_unique", status_code=302)

    return RedirectResponse(f"/picks?week={week.id}&ok=1", status_code=302)
