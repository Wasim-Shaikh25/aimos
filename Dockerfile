# Multi-stage build: dashboard first, then Python runtime.
# Paper mode by default; live is gated by mandate.yaml + the go-live ladder.

# ---- Stage 1: build the React dashboard ----
FROM node:20-alpine AS dashboard
WORKDIR /app/dashboard
COPY dashboard/package.json ./
RUN npm install
COPY dashboard/ ./
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.11-slim

# Install build deps for any wheels that need compilation (lightgbm optional).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency spec first for layer caching.
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e '.[serve,runtime,data]'

# Copy source and built dashboard.
COPY aimos/ ./aimos/
COPY scripts/ ./scripts/
COPY config/ ./config/
COPY specs/ ./specs/
COPY --from=dashboard /app/dashboard/dist ./dashboard/dist

# Runtime state, data, and journals.
RUN mkdir -p /app/state /app/data

EXPOSE 8000

ENV AIMOS_HOST=0.0.0.0
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request, os; urllib.request.urlopen('http://127.0.0.1:' + (os.environ.get('AIMOS_PORT') or os.environ.get('PORT', '8000')) + '/healthz').read();"

CMD ["python", "-m", "aimos.runtime.serve"]
