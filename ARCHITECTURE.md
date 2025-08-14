# Architecture Overview

This repository is organized for simplicity, small footprint, and self-hosting.

## Tech Stack
- Backend: FastAPI, SQLAlchemy, SQLite (default), Alembic (planned)
- Templates: Jinja2 + HTMX + Alpine.js + TailwindCSS (CDN)
- Scheduler: APScheduler (planned jobs)
- Logging: Python logging

## Structure
```
app/
  core/            # Settings, logging, templates, security
  db/              # Database engine/session helpers
  models/          # SQLAlchemy ORM models
  routers/         # FastAPI routers (auth, dashboard, profile, picks, history, admin)
  static/          # Static assets (JS, avatars defaults, logos)
  templates/       # Jinja2 templates
  main.py          # App entrypoint

assets/            # (Optional) logo assets to be copied
 data/             # DB, backups, avatars (gitkept)
```

## Key Modules
- `app/core/config.py` — environment configuration; no secrets hard-coded
- `app/core/security.py` — password hashing (argon2) and cookie session signer
- `app/core/logging.py` — basic structured logging
- `app/core/templates.py` — shared Jinja2 `templates` instance
- `app/db/session.py` — engine, session factory, `Base`
- `app/models/*` — ORM entities (User, Team, Season, Week, Game, Pick, TieBreaker)
- `app/routers/*` — endpoints grouped by feature
- `app/main.py` — FastAPI app, middleware, router inclusion

## Conventions
- Use snake_case for files and functions; PascalCase for classes
- Keep business logic in services (to be added under `app/services/`) rather than routers when it grows
- Avoid duplicate functions/names by checking existing modules first
- All user/route redirects should be explicit (avoid hidden side effects)

## Planned Services
- `providers/` — abstraction for schedule/scores (start with ESPN-like scoreboard)
- `services/` — domain logic for picks, standings, leaderboard, backups
- `admin/` — user/pick/database management logic

## Security Notes
- HTTP-only session cookies; set `secure` in production behind TLS
- CSRF tokens for POST forms (to be added)
- Rate limiting (optional, proxy-level)

## Data & Backups
- SQLite DB in `data/app.db`
- Avatars in `data/avatars/`
- Backups in `data/backups/`

## Deployment
- Dockerfile and docker-compose.yml for simple production
- Bare-metal via `uvicorn` + optional systemd unit
