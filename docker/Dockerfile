# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Multi-stage build: a fat builder that compiles wheels, and a slim runtime
# that carries only what is needed to serve — smaller image, faster cold start.
# ---------------------------------------------------------------------------

# --- Stage 1: builder ------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

# --- Stage 2: runtime ------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Run as an unprivileged user.
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY app ./app

USER app
EXPOSE 8000

# Container liveness maps to the /health endpoint.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
