# Contributing

Thanks for your interest in improving Office NFL Pickems!

## Development Setup

- Python 3.11 recommended
- Create a virtual environment and install deps:
  ```bash
  python3 -m venv .venv
  . .venv/bin/activate
  pip install -r requirements.txt
  ```
- Build CSS (for production-like testing):
  ```bash
  npm ci && npm run build:css
  ```
- Run the app:
  ```bash
  uvicorn app.main:app --host 0.0.0.0 --port 8000
  ```
- Or use Docker:
  ```bash
  docker compose up --build -d
  ```

## Code Style & Guidelines

- Keep functions small and focused; avoid duplication
- Add helpful logging for operational paths
- Update docs when adding features: `README.md`, `DEPLOYMENT.md`, `BACKUP.md`
- Prefer environment variables over hard-coded values

## Pull Requests

- Include a clear description and rationale
- Add screenshots for UI changes
- Note any security/privacy considerations
- Update documentation and `.env.example` if new config is introduced
- Reference related issues

## Issues

- Use issue templates (bug/feature)
- Provide reproducible steps and environment details
