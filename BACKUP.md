# Backup & Restore

## Overview

The app stores its data in `data/` (SQLite database, uploaded avatars, and backups).

You can manage backups from the Admin panel:

- Admin → Database → Create Backup: creates a `.tar.gz` including `app.db` and `avatars/` under `data/backups/`.
- Admin → Database → Download: download any existing backup archive.
- Admin → Database → Delete: remove a selected backup archive.
- Admin → Database → Restore (Dev Only): upload a raw SQLite `.db` to replace the current DB. A copy of the current DB is saved as `pre-restore-YYYYMMDD_HHMMSS.db` in `data/backups/`.
- Admin → Database → Restore from Archive (Dev Only): upload a `.tar.gz` created by this app to restore both the DB and the `avatars/` directory. The current DB is copied to `pre-restore-YYYYMMDD_HHMMSS.db`, and the current avatars are archived as `pre-restore-YYYYMMDD_HHMMSS-avatars.tar.gz`.
- Admin → Database → Clear (Dev Only): drops and recreates all tables.

Backups are also automated weekly via APScheduler (see below).

## Automated Weekly Backups

- A background scheduler creates a backup every Tuesday at 03:30 (local time), typically after Monday games have completed.
- The time zone is controlled by `PICKEMS_TIMEZONE` (defaults to system local when not set). Example: `America/Chicago`.
- Archives are stored under `data/backups/` with the name: `backup-YYYYMMDD_HHMMSS.tar.gz`.
- Consider setting up a cron or external process to sync `data/backups/` to off-machine storage.

### Retention

- The app prunes old backups automatically after each manual/scheduled backup.
- Configure how many most recent archives to keep via the environment variable `PICKEMS_BACKUPS_KEEP_LATEST` (default: `12`).

## Manual Backup

For a consistent snapshot when doing file-level copies:

1. Stop the app (or ensure no writes occur).
2. Copy the entire `data/` directory to a safe location.

## Restore

### From Admin UI (Dev Only)

1. Go to Admin → Database → Restore.
2. Upload a raw SQLite `.db` file.
3. The existing DB is first copied to `data/backups/pre-restore-*.db`, then replaced.

### From Archive (Dev Only)

1. Go to Admin → Database → Restore from Archive.
2. Upload a backup archive `.tar.gz` that was created by this app.
3. The existing DB is copied to `data/backups/pre-restore-*.db`, then replaced with the archived `app.db`.
4. If the archive contains `avatars/`, the current avatars directory is saved to `pre-restore-*-avatars.tar.gz`, then replaced.

### Production Restore

1. Stop the app service.
2. Replace `data/app.db` with the desired database file (and optionally restore `data/avatars/`).
3. Start the app service.
4. Verify by logging in and checking recent data.

## Notes & Recommendations

- Backup archives include `app.db` and `avatars/` only. You can extend the process as needed.
- Keep an eye on disk usage; tune `PICKEMS_BACKUPS_KEEP_LATEST` for retention to control space.
- Never upload or expose backups publicly; they contain sensitive data.
