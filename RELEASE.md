# Release Guide

This project uses semantic versioning via Git tags and builds multi-arch Docker images with GitHub Actions to GHCR.

## Pre-release checklist

- [ ] Back up current data from the running instance (`data/`), or download an Admin-created backup archive from Admin → Database
- [ ] Remove any development-only accounts (e.g., `admin/admin`) and ensure dev-only routes are disabled in production
- [ ] Set strong values in `.env` (e.g., `PICKEMS_SECRET_KEY`)
- [ ] Verify Tailwind CSS is built for bare-metal deployments (Docker images build CSS automatically)
- [ ] Verify scheduler timezone (`PICKEMS_TIMEZONE`) and backup retention (`PICKEMS_BACKUPS_KEEP_LATEST`)
- [ ] Review `DEPLOYMENT.md` for turn-up/turn-down notes
- [ ] Provider: confirm `PICKEMS_NFL_PROVIDER=espn` (default) and imported teams/schedule
- [ ] Live cache tuning: set `PICKEMS_LIVE_CACHE_TTL_SECONDS` and `PICKEMS_LIVE_NEGATIVE_TTL_SECONDS` as desired
- [ ] Admin backfill: verify a week backfill finalizes games (including preseason) via scoreboard fallback

## Versioning and tagging

1. Choose a version: `vX.Y.Z`
2. Tag and push:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
3. CI will build/push multi-arch images to GHCR: `ghcr.io/<owner>/<repo>:vX.Y.Z`

## Publishing a release

- Create a GitHub Release from the tag and include release notes
- Optionally attach `DEPLOYMENT.md`, `BACKUP.md` links and highlight major changes

## Turn up / Turn down (summary)

- Docker
  - Up: `docker compose up --build -d`
  - Down: `docker compose down`
- Bare-metal (systemd)
  - Start: `sudo systemctl start nfl-pickems`
  - Stop: `sudo systemctl stop nfl-pickems`

## Post-release

- [ ] Confirm `/healthz` and UI accessibility
- [ ] Run a test backup and verify retention
- [ ] Announce release and upgrade steps (if any)
