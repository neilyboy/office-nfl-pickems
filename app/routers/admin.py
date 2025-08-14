from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.templates import templates
from app.db.session import get_db
from app.deps.auth import get_current_user
from app.core.security import hash_password
from app.core.config import get_settings
import httpx
from app.services import backup as backup_service
from app.services.nfl import get_provider
from app.services.nfl.importer import upsert_teams_from_provider, import_week_schedule, refresh_team_logos, import_full_season
from app.services.logos import generate_offline_logos
from app.services.nfl.live import bulk_fetch_live_events
from app.models import User, Season, Week, Game, GameStatus, Team, Pick, TieBreaker

router = APIRouter()


@router.get("/admin", response_class=HTMLResponse)
def admin_index(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    return templates.TemplateResponse("admin/index.html", {"request": request, "title": "Admin", "current_user": user})


@router.get("/admin/nfl", response_class=HTMLResponse)
def admin_nfl_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    provider = get_provider()
    team_count = db.query(Team).count()
    default_year = datetime.now(timezone.utc).year
    return templates.TemplateResponse(
        "admin/nfl.html",
        {
            "request": request,
            "title": "NFL Data",
            "current_user": user,
            "provider_name": provider.name(),
            "team_count": team_count,
            "default_year": default_year,
        },
    )


@router.post("/admin/nfl/import-teams")
def admin_nfl_import_teams(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    provider = get_provider()
    inserted, updated = upsert_teams_from_provider(db, provider)
    return RedirectResponse(f"/admin/nfl?ok=teams&ins={inserted}&upd={updated}", status_code=302)


@router.post("/admin/nfl/import-week")
def admin_nfl_import_week(
    request: Request,
    season_year: int = Form(...),
    week_number: int = Form(...),
    season_type: int = Form(2),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    if season_year <= 0 or week_number <= 0:
        return RedirectResponse("/admin/nfl?err=bad_input", status_code=302)

    provider = get_provider()
    count = import_week_schedule(db, provider, season_year, week_number, season_type=season_type)
    return RedirectResponse(
        f"/admin/nfl?ok=week&count={count}&year={season_year}&wk={week_number}&stype={season_type}",
        status_code=302,
    )


@router.post("/admin/nfl/import-season")
def admin_nfl_import_season(
    request: Request,
    season_year: int = Form(...),
    include_preseason: int | None = Form(None),
    include_postseason: int | None = Form(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    if season_year <= 0:
        return RedirectResponse("/admin/nfl?err=bad_input", status_code=302)

    provider = get_provider()
    summary = import_full_season(
        db,
        provider,
        season_year,
        include_preseason=bool(include_preseason),
        include_postseason=bool(include_postseason),
    )
    return RedirectResponse(
        (
            f"/admin/nfl?ok=season&year={season_year}"
            f"&weeks={summary.get('weeks',0)}&total={summary.get('total',0)}"
            f"&pre={summary.get('pre',0)}&reg={summary.get('reg',0)}&post={summary.get('post',0)}"
        ),
        status_code=302,
    )


@router.post("/admin/nfl/generate-logos")
def admin_nfl_generate_logos(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    created, skipped = generate_offline_logos(db)
    return RedirectResponse(f"/admin/nfl?ok=logos&created={created}&skipped={skipped}", status_code=302)


@router.post("/admin/nfl/refresh-logos")
def admin_nfl_refresh_logos(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    provider = get_provider()
    updated, skipped = refresh_team_logos(db, provider)
    return RedirectResponse(f"/admin/nfl?ok=logos_refresh&updated={updated}&skipped={skipped}", status_code=302)


@router.post("/admin/nfl/backfill-week")
def admin_nfl_backfill_week(
    request: Request,
    season_year: int = Form(...),
    week_number: int = Form(...),
    season_type: int = Form(2),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    if season_year <= 0 or week_number <= 0:
        return RedirectResponse("/admin/nfl?err=bad_input", status_code=302)

    # Ensure season/week exist
    season = db.query(Season).filter(Season.year == season_year).first()
    if not season:
        return RedirectResponse("/admin/nfl?err=no_season", status_code=302)
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
        return RedirectResponse("/admin/nfl?err=no_week", status_code=302)

    # Optional: refresh schedule to attach provider IDs if missing/mismatched
    provider = get_provider()
    imported = import_week_schedule(db, provider, season_year, week_number, season_type=season_type)

    games = db.query(Game).filter(Game.week_id == week.id).all()
    event_ids = [g.provider_game_id for g in games if g.provider_game_id]

    updated = 0
    finalized = 0
    with_id = len(event_ids)

    if event_ids:
        # First attempt: ESPN event summaries (force-refresh)
        live = bulk_fetch_live_events(event_ids, force=True)
        for g in games:
            if not g.provider_game_id:
                continue
            lg = live.get(g.provider_game_id)
            if not lg:
                continue
            # Map state to internal status
            prev_status = g.status
            if lg.state == "in":
                g.status = GameStatus.IN_PROGRESS
            elif lg.state == "post":
                g.status = GameStatus.FINAL
            else:
                g.status = GameStatus.SCHEDULED
            if lg.home_score is not None:
                g.home_score = lg.home_score
            if lg.away_score is not None:
                g.away_score = lg.away_score
            if g.status != prev_status or lg.home_score is not None or lg.away_score is not None:
                db.add(g)
                updated += 1
            if g.status == GameStatus.FINAL:
                finalized += 1
        db.commit()

        # Fallback: If summaries were missing OR not-final (common for preseason),
        # query the scoreboard for the given week and update from there.
        remaining_ids = set()
        for g in games:
            eid = g.provider_game_id
            if not eid:
                continue
            lg = live.get(eid)
            if lg is None or lg.state != "post":
                remaining_ids.add(eid)
        if remaining_ids:
            settings = get_settings()
            base = settings.NFL_API_BASE or "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
            events = []
            params_used = None
            base_params = {
                "year": str(season_year),
                "week": str(week_number),
                "seasontype": str(season_type),
            }
            candidate_years = [season_year, season_year + 1]
            try:
                with httpx.Client(timeout=10) as client:
                    for y in candidate_years:
                        p = dict(base_params)
                        p["year"] = str(y)
                        try:
                            r = client.get(base, params=p)
                            r.raise_for_status()
                            d = r.json()
                            evs = d.get("events") or []
                            if evs:
                                events = evs
                                params_used = p
                                break
                            # fallback via dates
                            p2 = dict(base_params)
                            p2.pop("year", None)
                            p2["dates"] = str(y)
                            try:
                                r2 = client.get(base, params=p2)
                                r2.raise_for_status()
                                d2 = r2.json()
                                evs2 = d2.get("events") or []
                                if evs2:
                                    events = evs2
                                    params_used = p2
                                    break
                            except Exception:
                                pass
                        except Exception:
                            pass
            except Exception:
                events = []

            if events:
                # Build mapping event_id -> (state, home_score, away_score)
                sb_map = {}
                for ev in events:
                    try:
                        comps = (ev.get("competitions") or [])
                        if not comps:
                            continue
                        comp = comps[0]
                        st = ((comp.get("status") or {}).get("type") or {}).get("state")
                        competitors = comp.get("competitors") or []
                        hs = None
                        as_ = None
                        for c in competitors:
                            score_val = c.get("score")
                            try:
                                score_val = int(score_val) if score_val is not None else None
                            except Exception:
                                score_val = None
                            if c.get("homeAway") == "home":
                                hs = score_val
                            elif c.get("homeAway") == "away":
                                as_ = score_val
                        eid = str(ev.get("id")) if ev.get("id") else None
                        if eid:
                            sb_map[eid] = (st, hs, as_)
                    except Exception:
                        continue

                for g in games:
                    if not g.provider_game_id:
                        continue
                    if g.provider_game_id not in remaining_ids:
                        continue
                    row = sb_map.get(g.provider_game_id)
                    if not row:
                        continue
                    st, hs, as_ = row
                    prev_status = g.status
                    if st == "in":
                        g.status = GameStatus.IN_PROGRESS
                    elif st == "post":
                        g.status = GameStatus.FINAL
                    elif st == "pre":
                        g.status = GameStatus.SCHEDULED
                    if hs is not None:
                        g.home_score = hs
                    if as_ is not None:
                        g.away_score = as_
                    if g.status != prev_status or hs is not None or as_ is not None:
                        db.add(g)
                        updated += 1
                    if g.status == GameStatus.FINAL:
                        finalized += 1
                db.commit()

    total = len(games)
    return RedirectResponse(
        (
            f"/admin/nfl?ok=backfill&year={season_year}&wk={week_number}&stype={season_type}"
            f"&total={total}&withid={with_id}&updated={updated}&final={finalized}&imported={imported}"
        ),
        status_code=302,
    )


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    users = db.query(User).order_by(User.username.asc()).all()
    return templates.TemplateResponse(
        "admin/users.html",
        {"request": request, "title": "Users", "current_user": user, "users": users},
    )


@router.post("/admin/users/create")
def admin_users_create(
    request: Request,
    username: str = Form(...),
    password: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    is_admin: int = Form(0),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    if db.query(User.id).filter(User.username == username).first():
        return RedirectResponse("/admin/users?err=exists", status_code=302)

    new_user = User(
        username=username.strip(),
        password_hash=hash_password(password or "TempPass123!"),
        first_name=(first_name or "").strip(),
        last_name=(last_name or "").strip(),
        is_admin=bool(is_admin),
        must_change_password=True,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse("/admin/users?ok=1", status_code=302)


@router.get("/admin/users/{user_id}", response_class=HTMLResponse)
def admin_user_edit_page(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse("/admin/users?err=notfound", status_code=302)

    return templates.TemplateResponse(
        "admin/edit_user.html",
        {"request": request, "title": f"Edit {target.username}", "current_user": user, "u": target},
    )


@router.post("/admin/users/{user_id}/update")
def admin_user_update(
    user_id: int,
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    is_admin: int = Form(0),
    must_change_password: int = Form(0),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse("/admin/users?err=notfound", status_code=302)

    target.first_name = (first_name or "").strip()
    target.last_name = (last_name or "").strip()
    target.is_admin = bool(is_admin)
    target.must_change_password = bool(must_change_password)
    if password:
        target.password_hash = hash_password(password)
        target.must_change_password = True
    db.add(target)
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}?ok=1", status_code=302)


@router.post("/admin/users/{user_id}/delete")
def admin_user_delete(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse("/admin/users?err=notfound", status_code=302)
    # Prevent deleting yourself to avoid lockout
    if target.id == user.id:
        return RedirectResponse("/admin/users?err=cant_delete_self", status_code=302)

    db.delete(target)
    db.commit()
    return RedirectResponse("/admin/users?ok=deleted", status_code=302)


@router.post("/admin/dev/seed-sample")
def admin_dev_seed_sample(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    settings = get_settings()
    if settings.ENV != "development":
        return RedirectResponse("/admin?err=dev_only", status_code=302)

    # Ensure some teams
    logos = {
        "NE": "/static/logos/NE.svg",
        "DAL": "/static/logos/DAL.svg",
        "SF": "/static/logos/SF.svg",
        "KC": "/static/logos/KC.svg",
    }

    def team(abbr: str, name: str, location: str) -> Team:
        t = db.query(Team).filter(Team.abbr == abbr).first()
        if t:
            # Populate a logo path if missing (for demo UI)
            if not t.logo_path and abbr in logos:
                t.logo_path = logos[abbr]
                db.add(t)
            return t
        t = Team(slug=abbr.lower(), name=name, location=location, abbr=abbr)
        # Set logo for dev/demo teams
        if abbr in logos:
            t.logo_path = logos[abbr]
        db.add(t)
        db.flush()
        return t

    t_ne = team("NE", "Patriots", "New England")
    t_dal = team("DAL", "Cowboys", "Dallas")
    t_sf = team("SF", "49ers", "San Francisco")
    t_kc = team("KC", "Chiefs", "Kansas City")

    # Season
    year = datetime.now(timezone.utc).year
    season = db.query(Season).filter(Season.year == year).first()
    if not season:
        season = Season(year=year, is_active=True)
        db.add(season)
        db.flush()

    # Week 1 with kickoff in ~30 minutes (unlocked until then). If it already exists,
    # bump the kickoff into the near future so picks are unlocked.
    week = db.query(Week).filter(Week.season_id == season.id, Week.week_number == 1).first()
    now_utc = datetime.now(timezone.utc)
    if not week:
        week = Week(season_id=season.id, week_number=1, first_kickoff_at=now_utc + timedelta(minutes=30))
        db.add(week)
        db.flush()
    else:
        week.first_kickoff_at = now_utc + timedelta(minutes=30)
        db.add(week)

    # Create a few games if none exist yet for this week; otherwise bump non-final games forward
    existing_games = db.query(Game).filter(Game.week_id == week.id).count()
    base = now_utc + timedelta(minutes=45)
    if existing_games == 0:
        games = [
            Game(season_id=season.id, week_id=week.id, home_team_id=t_ne.id, away_team_id=t_dal.id, start_time=base),
            Game(season_id=season.id, week_id=week.id, home_team_id=t_sf.id, away_team_id=t_kc.id, start_time=base + timedelta(hours=1)),
            Game(season_id=season.id, week_id=week.id, home_team_id=t_dal.id, away_team_id=t_sf.id, start_time=base + timedelta(hours=2)),
        ]
        db.add_all(games)
    else:
        games = db.query(Game).filter(Game.week_id == week.id).order_by(Game.start_time.asc()).all()
        for idx, g in enumerate(games):
            if g.status != GameStatus.FINAL:
                g.start_time = base + timedelta(hours=idx)
                g.home_score = 0
                g.away_score = 0
                g.status = GameStatus.SCHEDULED
                db.add(g)

    db.commit()
    return RedirectResponse(f"/picks?week={week.id}&ok=seeded", status_code=302)


@router.get("/admin/dev/games", response_class=HTMLResponse)
def admin_dev_games(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    settings = get_settings()
    if settings.ENV != "development":
        return RedirectResponse("/admin?err=dev_only", status_code=302)

    games = db.query(Game).order_by(Game.start_time.desc()).limit(25).all()
    # Collect team ids
    team_ids = set()
    for g in games:
        team_ids.add(g.home_team_id)
        team_ids.add(g.away_team_id)
    teams = db.query(Team).filter(Team.id.in_(list(team_ids))).all() if team_ids else []
    teams_by_id = {t.id: t for t in teams}

    return templates.TemplateResponse(
        "admin/dev_games.html",
        {
            "request": request,
            "title": "Dev: Games",
            "current_user": user,
            "games": games,
            "teams_by_id": teams_by_id,
        },
    )


@router.post("/admin/dev/finalize-game/{game_id}")
def admin_dev_finalize_game(
    game_id: int,
    request: Request,
    home: int = Form(0),
    away: int = Form(0),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    settings = get_settings()
    if settings.ENV != "development":
        return RedirectResponse("/admin?err=dev_only", status_code=302)

    g = db.query(Game).filter(Game.id == game_id).first()
    if not g:
        return RedirectResponse("/admin/dev/games?err=notfound", status_code=302)

    try:
        g.home_score = int(home)
        g.away_score = int(away)
    except Exception:
        return RedirectResponse("/admin/dev/games?err=badscore", status_code=302)

    g.status = GameStatus.FINAL
    db.add(g)
    db.commit()
    return RedirectResponse("/admin/dev/games?ok=finalized", status_code=302)


@router.post("/admin/dev/clear-seeded")
def admin_dev_clear_seeded(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    settings = get_settings()
    if settings.ENV != "development":
        return RedirectResponse("/admin?err=dev_only", status_code=302)

    # Target current season, Week 1, dev-seeded game pairs
    year = datetime.now(timezone.utc).year
    season = db.query(Season).filter(Season.year == year).first()
    if not season:
        return RedirectResponse("/admin/dev/games?ok=cleared", status_code=302)

    week = (
        db.query(Week)
        .filter(Week.season_id == season.id, Week.week_number == 1)
        .first()
    )
    if not week:
        return RedirectResponse("/admin/dev/games?ok=cleared", status_code=302)

    # Resolve team IDs for known dev teams
    wanted_abbrs = ["NE", "DAL", "SF", "KC"]
    teams = db.query(Team).filter(Team.abbr.in_(wanted_abbrs)).all()
    ids = {t.abbr: t.id for t in teams}

    # Build the seeded game pair set using available teams
    target_pairs = set()
    def add_pair(a: str, b: str):
        if a in ids and b in ids:
            target_pairs.add(frozenset({ids[a], ids[b]}))

    add_pair("NE", "DAL")
    add_pair("SF", "KC")
    add_pair("DAL", "SF")

    # Nothing to do if pairs not resolvable
    if not target_pairs:
        return RedirectResponse("/admin/dev/games?ok=cleared", status_code=302)

    # Find candidate games: Week 1 of current season with no provider_game_id
    candidates = (
        db.query(Game)
        .filter(
            Game.week_id == week.id,
            Game.provider_game_id.is_(None),
        )
        .all()
    )

    deleted = 0
    for g in candidates:
        pair = frozenset({g.home_team_id, g.away_team_id})
        if pair in target_pairs:
            db.delete(g)
            deleted += 1

    db.commit()
    return RedirectResponse(f"/admin/dev/games?ok=cleared&n={deleted}", status_code=302)


# ------------------------------
# Database management (Admin)
# ------------------------------


@router.get("/admin/db", response_class=HTMLResponse)
def admin_db_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    settings = get_settings()
    backups = backup_service.list_backups()
    return templates.TemplateResponse(
        "admin/db.html",
        {
            "request": request,
            "title": "Database",
            "current_user": user,
            "env": settings.ENV,
            "backups": backups,
        },
    )


@router.post("/admin/db/backup")
def admin_db_backup(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    backup_service.create_backup()
    backup_service.prune_backups()
    return RedirectResponse("/admin/db?ok=backup", status_code=302)


@router.get("/admin/db/backup/{name}")
def admin_db_download(name: str, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    # Prevent path traversal
    if not name.endswith(".tar.gz"):
        return RedirectResponse("/admin/db?err=badname", status_code=302)
    fp = (backup_service.backups_dir() / name).resolve()
    if fp.parent != backup_service.backups_dir().resolve() or not fp.exists():
        return RedirectResponse("/admin/db?err=notfound", status_code=302)
    return FileResponse(fp.as_posix(), media_type="application/gzip", filename=name)


@router.post("/admin/db/delete/{name}")
def admin_db_delete_backup(name: str, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    if not name.endswith(".tar.gz"):
        return RedirectResponse("/admin/db?err=badname", status_code=302)
    fp = (backup_service.backups_dir() / name).resolve()
    if fp.parent != backup_service.backups_dir().resolve() or not fp.exists():
        return RedirectResponse("/admin/db?err=notfound", status_code=302)
    try:
        fp.unlink()
    except Exception:
        return RedirectResponse("/admin/db?err=delete_failed", status_code=302)
    return RedirectResponse("/admin/db?ok=deleted", status_code=302)


@router.post("/admin/db/restore")
def admin_db_restore(request: Request, upload: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    settings = get_settings()
    if settings.ENV != "development":
        return RedirectResponse("/admin/db?err=dev_only", status_code=302)

    # Only allow raw SQLite DB file uploads for now
    try:
        backup_service.restore_sqlite_db_from_fileobj(upload.file)
    except ValueError:
        return RedirectResponse("/admin/db?err=bad_file", status_code=302)
    return RedirectResponse("/admin/db?ok=restored", status_code=302)


@router.post("/admin/db/restore-archive")
def admin_db_restore_archive(request: Request, upload: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    settings = get_settings()
    if settings.ENV != "development":
        return RedirectResponse("/admin/db?err=dev_only", status_code=302)

    try:
        backup_service.restore_from_archive(upload.file)
    except ValueError:
        return RedirectResponse("/admin/db?err=bad_archive", status_code=302)
    except Exception:
        return RedirectResponse("/admin/db?err=bad_archive", status_code=302)
    return RedirectResponse("/admin/db?ok=restored", status_code=302)


@router.post("/admin/db/clear")
def admin_db_clear(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    settings = get_settings()
    if settings.ENV != "development":
        return RedirectResponse("/admin/db?err=dev_only", status_code=302)

    # Drop and recreate all tables
    backup_service.clear_database()
    return RedirectResponse("/admin/db?ok=cleared", status_code=302)


# ------------------------------
# Pick management (Admin)
# ------------------------------


def _get_current_week(db: Session) -> Week | None:
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


@router.get("/admin/picks", response_class=HTMLResponse)
def admin_picks_page(request: Request, user_id: int | None = None, week: int | None = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    # Users for selector
    users = db.query(User).order_by(User.username.asc()).all()
    if not users:
        return templates.TemplateResponse(
            "admin/picks.html",
            {
                "request": request,
                "title": "Pick Management",
                "current_user": user,
                "users": [],
                "selected_user": None,
                "weeks": [],
                "selected_week": None,
            },
        )

    selected_user = None
    if user_id is not None:
        selected_user = db.query(User).filter(User.id == user_id).first()
    if not selected_user:
        selected_user = users[0]

    # Determine selected week
    selected_week: Week | None = None
    if week is not None:
        selected_week = db.query(Week).filter(Week.id == week).first()
    if not selected_week:
        selected_week = _get_current_week(db)

    # Build weeks list (entire season across all segments)
    weeks = (
        db.query(Week)
        .filter(Week.season_id == selected_week.season_id)
        .order_by(Week.season_type, Week.week_number)
        .all()
        if selected_week
        else []
    )

    # Prev/Next helpers
    prev_week = None
    next_week = None
    if selected_week and weeks:
        try:
            idx = [w.id for w in weeks].index(selected_week.id)
            if idx > 0:
                prev_week = weeks[idx - 1]
            if idx < len(weeks) - 1:
                next_week = weeks[idx + 1]
        except ValueError:
            pass

    # Games list
    games = (
        db.query(Game).filter(Game.week_id == selected_week.id).order_by(Game.start_time).all()
        if selected_week
        else []
    )

    # Existing picks for selected user
    game_ids = [g.id for g in games]
    existing_picks: dict[int, int] = {}
    if game_ids:
        rows = db.query(Pick).filter(Pick.user_id == selected_user.id, Pick.game_id.in_(game_ids)).all()
        existing_picks = {p.game_id: p.chosen_team_id for p in rows}

    # Teams lookup
    team_ids = set()
    for g in games:
        team_ids.add(g.home_team_id)
        team_ids.add(g.away_team_id)
    teams_by_id = {t.id: t for t in db.query(Team).filter(Team.id.in_(list(team_ids))).all()} if team_ids else {}

    # Tiebreaker for selected user/week
    tb_guess = None
    if selected_week:
        tb = (
            db.query(TieBreaker)
            .filter(TieBreaker.user_id == selected_user.id, TieBreaker.week_id == selected_week.id)
            .first()
        )
        if tb:
            tb_guess = tb.guess_points

    # Admin override: allow editing regardless of lock state
    locked = False

    ctx = {
        "request": request,
        "title": "Pick Management",
        "current_user": user,
        "users": users,
        "selected_user": selected_user,
        "weeks": weeks,
        "selected_week": selected_week,
        "games": games,
        "teams_by_id": teams_by_id,
        "existing_picks": existing_picks,
        "tb_guess": tb_guess,
        "locked": locked,
        "prev_week": prev_week,
        "next_week": next_week,
        "err": request.query_params.get("err"),
        "ok": request.query_params.get("ok"),
    }
    return templates.TemplateResponse("admin/picks.html", ctx)


@router.get("/admin/picks/content", response_class=HTMLResponse)
def admin_picks_content(request: Request, user_id: int | None = None, week: int | None = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    users = db.query(User).order_by(User.username.asc()).all()
    if not users:
        return templates.TemplateResponse(
            "admin/picks_content.html",
            {
                "request": request,
                "users": [],
                "selected_user": None,
                "weeks": [],
                "selected_week": None,
                "games": [],
                "teams_by_id": {},
                "existing_picks": {},
                "tb_guess": None,
                "locked": True,
                "prev_week": None,
                "next_week": None,
            },
            headers={"HX-Push-Url": "/admin/picks"},
        )

    selected_user = None
    if user_id is not None:
        selected_user = db.query(User).filter(User.id == user_id).first()
    if not selected_user:
        selected_user = users[0]

    selected_week: Week | None = None
    if week is not None:
        selected_week = db.query(Week).filter(Week.id == week).first()
    if not selected_week:
        selected_week = _get_current_week(db)

    weeks = (
        db.query(Week)
        .filter(Week.season_id == selected_week.season_id)
        .order_by(Week.season_type, Week.week_number)
        .all()
        if selected_week
        else []
    )

    prev_week = None
    next_week = None
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
    existing_picks: dict[int, int] = {}
    if game_ids:
        rows = db.query(Pick).filter(Pick.user_id == selected_user.id, Pick.game_id.in_(game_ids)).all()
        existing_picks = {p.game_id: p.chosen_team_id for p in rows}

    team_ids = set()
    for g in games:
        team_ids.add(g.home_team_id)
        team_ids.add(g.away_team_id)
    teams_by_id = {t.id: t for t in db.query(Team).filter(Team.id.in_(list(team_ids))).all()} if team_ids else {}

    tb_guess = None
    if selected_week:
        tb = (
            db.query(TieBreaker)
            .filter(TieBreaker.user_id == selected_user.id, TieBreaker.week_id == selected_week.id)
            .first()
        )
        if tb:
            tb_guess = tb.guess_points

    # Admin override: allow editing regardless of lock state
    locked = False

    ctx = {
        "request": request,
        "users": users,
        "selected_user": selected_user,
        "weeks": weeks,
        "selected_week": selected_week,
        "games": games,
        "teams_by_id": teams_by_id,
        "existing_picks": existing_picks,
        "tb_guess": tb_guess,
        "locked": locked,
        "prev_week": prev_week,
        "next_week": next_week,
        "err": request.query_params.get("err"),
        "ok": request.query_params.get("ok"),
    }
    push_url = f"/admin/picks?user_id={selected_user.id}&week={selected_week.id}" if selected_user and selected_week else "/admin/picks"
    return templates.TemplateResponse("admin/picks_content.html", ctx, headers={"HX-Push-Url": push_url})


@router.post("/admin/picks/save")
async def admin_picks_save(
    request: Request,
    user_id: int = Form(...),
    week_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.is_admin:
        return RedirectResponse("/dashboard", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/profile/change-password?force=1", status_code=302)

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        return RedirectResponse("/admin/picks?err=nouser", status_code=302)

    week = db.query(Week).filter(Week.id == week_id).first()
    if not week:
        return RedirectResponse(f"/admin/picks?user_id={target_user.id}&err=noweek", status_code=302)

    form = await request.form()

    # Collect picks
    picks_posted: dict[int, int] = {}
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

    games = db.query(Game).filter(Game.id.in_(game_ids), Game.week_id == week.id).all() if game_ids else []
    valid_game_ids = {g.id for g in games}
    for gid in list(picks_posted.keys()):
        if gid not in valid_game_ids:
            picks_posted.pop(gid, None)

    if picks_posted:
        existing = (
            db.query(Pick)
            .filter(Pick.user_id == target_user.id, Pick.game_id.in_(list(picks_posted.keys())))
            .all()
        )
        by_gid = {p.game_id: p for p in existing}
        for g in games:
            if g.id not in picks_posted:
                continue
            chosen_team_id = picks_posted[g.id]
            if chosen_team_id not in (g.home_team_id, g.away_team_id):
                continue
            row = by_gid.get(g.id)
            if row:
                row.chosen_team_id = chosen_team_id
            else:
                db.add(Pick(user_id=target_user.id, game_id=g.id, chosen_team_id=chosen_team_id))

    # Tiebreaker
    tb_val_raw = form.get("tiebreaker")
    if tb_val_raw is not None and str(tb_val_raw).strip() != "":
        try:
            tb_val = int(str(tb_val_raw).strip())
            if tb_val < 0:
                return RedirectResponse(f"/admin/picks?user_id={target_user.id}&week={week.id}&err=tb_invalid", status_code=302)
        except Exception:
            return RedirectResponse(f"/admin/picks?user_id={target_user.id}&week={week.id}&err=tb_invalid", status_code=302)

        existing_tb = (
            db.query(TieBreaker).filter(TieBreaker.user_id == target_user.id, TieBreaker.week_id == week.id).first()
        )
        if existing_tb:
            existing_tb.guess_points = tb_val
        else:
            db.add(TieBreaker(user_id=target_user.id, week_id=week.id, guess_points=tb_val))

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse(f"/admin/picks?user_id={target_user.id}&week={week.id}&err=tb_unique", status_code=302)

    return RedirectResponse(f"/admin/picks?user_id={target_user.id}&week={week.id}&ok=1", status_code=302)
