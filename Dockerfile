# syntax=docker/dockerfile:1

# ---- Frontend build stage: compile Tailwind CSS ----
FROM node:20-alpine AS frontend
WORKDIR /build
# Copy full repo so Tailwind can scan templates for classes
COPY . .
RUN npm ci && npm run build:css

# ---- Final runtime image ----
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .
# Overwrite compiled CSS from builder to ensure production bundle present
COPY --from=frontend /build/app/static/app.css /app/app/static/app.css

EXPOSE 8000

VOLUME ["/app/data", "/app/logs"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys,socket; socket.setdefaulttimeout(2);\n\ntry:\n    urllib.request.urlopen('http://127.0.0.1:8000/healthz'); sys.exit(0)\nexcept Exception:\n    sys.exit(1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
