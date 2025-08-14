# Deployment Guide

This app runs on Raspberry Pi (ARM) and Ubuntu.

## Option A: Docker Compose

1. Install Docker + Compose
2. (Optional) Create `.env` from `.env.example`
3. Start:
   ```bash
docker compose up --build -d
```
App runs at http://localhost:${HOST_PORT:-8000}. Set `HOST_PORT` in `.env` to change the host port mapping.
4. Visit `http://<host>:${HOST_PORT:-8000}` and create the admin.

### Reverse Proxy (Caddy sample)

```
:80 {
  reverse_proxy 127.0.0.1:${HOST_PORT:-8000}
}
```

For HTTPS, use your domain and `:443` with `tls` configured.

### Reverse Proxy (nginx sample)

```
server {
  listen 80;
  server_name your.domain;

  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 10m; # avatar uploads
  }
}
```

Health endpoint: `GET /healthz` returns `ok`.

## Front-end CSS (Tailwind)

- In development, templates load Tailwind via CDN (controlled by `IS_DEV`).
- In production, you must compile the CSS once to `app/static/app.css`:

```bash
npm ci
npm run build:css
```

- Docker builds: ensure `app/static/app.css` exists before running `docker compose up --build`, or extend the Dockerfile to build CSS inside the image.
- Bare-metal: run the build after pulling updates and before restarting the service.

## Option B: Bare-metal (systemd)

1. Install Python 3.11
2. Create venv and install requirements. Also build the CSS bundle once:
   ```bash
   # from project root
   python3 -m venv .venv && . .venv/bin/activate
   pip install -r requirements.txt
   npm ci && npm run build:css
   ```
3. Create a systemd unit `/etc/systemd/system/nfl-pickems.service`:

```
[Unit]
Description=Office NFL Pickems
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/office-nfl-pickems
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/opt/office-nfl-pickems/.env
ExecStart=/opt/office-nfl-pickems/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

4. Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nfl-pickems
```

### Turn up / Turn down

- Docker
  - Up: `docker compose up --build -d`
  - Down (stop containers): `docker compose down`
  - Down and delete volumes (DESTRUCTIVE): `docker compose down -v`
  - Logs: `docker compose logs -f`
- Bare-metal (systemd)
  - Start: `sudo systemctl start nfl-pickems`
  - Stop: `sudo systemctl stop nfl-pickems`
  - Status: `systemctl status nfl-pickems`

## Data & Backups

- Data lives in `data/` (SQLite DB, avatars, backups)
- Admin UI: Admin → Database lets you Create/Download backups. In development you can also Restore a raw `.db`, Restore from Archive (`.tar.gz`), and Clear tables.
- Automated weekly backup runs every Tuesday at 03:30 (local time). Configure timezone via `PICKEMS_TIMEZONE`.
- Offsite retention is recommended: periodically sync `data/backups/` to external storage.

### Raspberry Pi (ARM) notes

- Compose builds on-device for the current architecture (ARMv8/ARMv7) by default; no special flags required.
- The provided multi-stage Dockerfile compiles Tailwind CSS in a Node builder stage (arm images available) and ships a slim Python runtime.
- If you prefer building multi-arch images on an x86 host, use Docker Buildx:

```bash
docker buildx create --use
docker buildx build --platform linux/amd64,linux/arm64 -t <your-registry>/nfl-pickems:latest --push .
```

## CI/CD (GitHub Actions + GHCR)

This repo includes a workflow at `.github/workflows/docker.yml` that builds and pushes multi-arch images to GitHub Container Registry (GHCR) on pushes to the default branch and on tags (`v*.*.*`).

- Images are published to `ghcr.io/<owner>/<repo>:<tag>`.
- Default tags include branch, tag, SHA, and `latest` for the default branch.
- The workflow uses `GITHUB_TOKEN` and requires that GHCR packages are enabled for the repo/org.

Pull and run from GHCR:

```bash
docker pull ghcr.io/<owner>/<repo>:latest
docker run --rm -p 8000:8000 ghcr.io/<owner>/<repo>:latest
```

Using Compose with GHCR image:

```yaml
services:
  web:
    image: ghcr.io/<owner>/<repo>:latest
    env_file: .env
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    restart: unless-stopped
```

## Environment Variables

These can be set in your shell, Compose file, systemd unit, or `.env` file (see `.env.example`). All variables use the `PICKEMS_` prefix.

- `PICKEMS_ENV` (development|production|test). Default: development
- `PICKEMS_LOG_LEVEL` (e.g., INFO, DEBUG). Default: INFO
- `PICKEMS_DATABASE_URL` (default SQLite in `data/app.db`)
- `PICKEMS_SECRET_KEY` (override in production)
- `PICKEMS_SESSION_COOKIE_NAME` (optional)
- `PICKEMS_TIMEZONE` (IANA tz like `America/Chicago`, or `local`). Affects scheduler
- `PICKEMS_BACKUPS_KEEP_LATEST` (int). How many recent backup archives to retain. Default: 12
- `HOST_PORT` Host port for Docker Compose mapping (`${HOST_PORT}:8000`). Default: 8000
- `PICKEMS_NFL_PROVIDER` Provider selection. Default: `espn` (uses public ESPN for schedules + logos). Alternative: `local_dict` (offline only)
- `PICKEMS_NFL_API_BASE` Optional override for ESPN scoreboard base URL. Normally leave unset.
- `PICKEMS_LIVE_CACHE_TTL_SECONDS` TTL (seconds) for in-memory live summary cache. Default: `15`. Lower = more frequent external refresh, higher = fewer calls.
- `PICKEMS_LIVE_NEGATIVE_TTL_SECONDS` TTL (seconds) to suppress repeated fetches for missing/invalid ESPN event IDs (404/410). Default: `600`.

## Logs

- Docker: logs via `docker logs`
- Bare-metal: stdout (use systemd journal)

## Troubleshooting

- CSS missing in production: ensure `app/static/app.css` exists. With Docker, the multi-stage build handles this. For bare-metal, run `npm ci && npm run build:css`.
- Cannot download backups behind proxy: ensure reverse proxy allows `application/gzip` and large files; set `client_max_body_size` accordingly in nginx.
- Healthcheck failing: hit `http://<host>:8000/healthz` directly; verify the app is running and the reverse proxy forwards correctly.
