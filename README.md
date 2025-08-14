# Office NFL Pickems (Self-hosted)

Dark, modern, self-hosted NFL pickems web app. Runs on Raspberry Pi or Ubuntu. First run prompts you to create an admin user. Only admins manage users. Weekly picks lock at first kickoff (Thu). Tie-breaker is total Monday points (unique per week).

## Quick Start (Bare‑metal)

1. Python 3.11 recommended
2. Create venv and install deps:
   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   ```
3. (Production only) Build CSS once:
   ```bash
   npm ci && npm run build:css
   ```
4. Run the app:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
5. Open http://localhost:8000 and complete admin setup

## Quick Start (Docker)

```bash
docker compose up --build -d
```
App runs at http://localhost:${HOST_PORT:-8000}. Set `HOST_PORT` in `.env` to change the host port mapping.

## Raspberry Pi Quick Start (Preseason Week 3)

Follow the Bare‑metal Quick Start above. Then in the UI:

1. Admin → NFL Data → Import Teams (loads ESPN team data + logos)
2. Admin → NFL Data → Import Week
   - Season Year: 2025
   - Season Type: Preseason
   - Week: 3
3. Create users (Admin → Users) or share credentials
4. Have users make picks before the first kickoff (lockout at first game)
5. Live scoreboard will auto‑refresh during games; after games, Admin → NFL Data → Backfill Week Results (only if needed) will finalize scores

Notes:
- Default provider is ESPN; offline SVG logos are available via Admin → NFL Data → Generate Offline Logos if running air‑gapped.
- Live cache TTLs are adjustable via env: see below.

## Configuration

Copy `.env.example` to `.env` and adjust values. Environment variables use `PICKEMS_` prefix. Data stored in `./data`.

### Live scoreboard cache/refresh

- `PICKEMS_LIVE_CACHE_TTL_SECONDS` (default `15`): TTL for ESPN live summary cache.
  - Lower for snappier updates; higher to reduce external API calls.
- `PICKEMS_LIVE_NEGATIVE_TTL_SECONDS` (default `600`): Suppress repeated 404/410 summary fetches by negative-caching bad ESPN event IDs for this long.
- The dashboard live fragment auto-refreshes faster when any game is live (every 15s) and slower otherwise (every 60s).

### NFL Data Provider (default: ESPN)

- Provider selection: `PICKEMS_NFL_PROVIDER=espn` (default) or `local_dict`.
- ESPN uses public endpoints for schedules and official team logos.
- Local dict uses the built-in team list; logos fall back to offline SVGs.
- Admin backfill forces a fresh live fetch and falls back to the ESPN weekly scoreboard for any missing or non‑final summaries (preseason‑safe).

After switching or on first run, go to Admin → NFL Data:

- Import Teams: pulls team metadata and ESPN logo URLs (with ESPN provider).
- Import Week: imports a specific `season year` + `week` schedule from ESPN.
- Import Full Season: loops across preseason (optional), regular (1–18), and postseason (optional) weeks and upserts all games.
- Refresh ESPN Logos: updates only stored ESPN logo URLs for all teams without changing names/aliases.

Optional fallback: Admin → NFL Data → Generate Offline Logos creates local SVGs for all teams for offline use.

## Features

- First‑run admin setup (`/setup-admin`)
- Authentication with admin role and must‑change‑password enforcement
- Weekly picks with lockout at first kickoff and unique Monday tiebreaker validation
- Dashboard with live status, leaderboard, and lunch winner/loser
- User profile with avatar upload/crop and deterministic default avatars
- Admin: user management; picks management; database management
  - Create/Download/Delete backups, human‑readable sizes
  - Automated weekly backups via scheduler (Tue 03:30 local) with retention
  - Dev‑only: Restore raw `.db`, Restore from Archive (`.tar.gz` DB+avatars), Clear DB
- SQLite by default, data stored in `data/` (db, avatars, backups)
- Dark, modern UI using Tailwind, HTMX, Alpine.js

## Production Notes

- See `DEPLOYMENT.md` for Docker Compose and bare‑metal (systemd) guides, reverse proxy samples, healthchecks, Raspberry Pi notes, and turn‑up/turn‑down instructions.
- See `BACKUP.md` for backup/restore, retention, and operational guidance.

## Contributing and Releases

- See `CONTRIBUTING.md` for local setup and PR guidelines
- See `RELEASE.md` for versioning, tagging, and turn up/down checklist
- See `SECURITY.md` for reporting vulnerabilities and secret management
- See `CODE_OF_CONDUCT.md` for community guidelines

## Logs

Readable logs to stdout by default. For Docker, mount `./logs` if you want to store logs.

## Security

- No secrets in code; use env vars
- HTTP-only cookie sessions
- Consider TLS via a reverse proxy (e.g., Caddy/Traefik)

## License

MIT
