# Data Sources

The app uses a provider abstraction to fetch schedule, scores, and team info.

## Default: ESPN

- Set via `PICKEMS_NFL_PROVIDER=espn` (default). No API key required.
- Schedules, scores, and official team logos come from ESPN public endpoints.
- Live summaries are cached in-memory (`PICKEMS_LIVE_CACHE_TTL_SECONDS`), and missing/invalid event IDs are negative‑cached (`PICKEMS_LIVE_NEGATIVE_TTL_SECONDS`).
- Admin backfill first forces a fresh live fetch and then falls back to the weekly scoreboard for any missing or non‑final summaries (preseason‑safe).

## Offline/air‑gapped: local_dict

- Use `PICKEMS_NFL_PROVIDER=local_dict` to rely on a local team dictionary.
- Logos can be generated offline via Admin → NFL Data → Generate Offline Logos.

## Goals

- Swappable via config
- No hard‑coded secrets in repo
- Respect rate limits; cache appropriately
