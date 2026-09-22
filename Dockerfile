
#############################
# Stage 1: builder
#############################
FROM python:3.11-slim-bookworm AS builder

# Don't write .pyc, flush stdout/stderr immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# All deps in requirements.txt (psycopg2-binary, bcrypt, cryptography) ship prebuilt
# manylinux wheels, so no compiler / libpq-dev needed even in the builder stage.
# Create a venv so we can copy just the venv into the final image cleanly
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only requirements first -> layer caching: deps rebuild only when this changes
COPY requirements.txt .
# BuildKit cache mount: pip's download cache persists across builds (faster rebuilds)
# without that cache ending up in the final image (builder stage is discarded).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

#############################
# Stage 2: runtime (final image)
#############################
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_HOME=/app

# psycopg2-binary bundles its own libpq, so ZERO extra apt packages are needed
# in the runtime image. No curl either -- HEALTHCHECK below uses Python's stdlib
# instead, so the final image installs nothing beyond the base python:slim layer.
# Smaller image = fewer packages = fewer CVEs to patch.

# Non-root, no-login system user (can't be used to get an interactive shell,
# has no home dir to write to, can't sudo -- least privilege)
RUN groupadd --gid 1000 luxus \
    && useradd --uid 1000 --gid luxus --shell /usr/sbin/nologin --no-create-home luxus

# Bring in the pre-built virtualenv from the builder stage (no pip/gcc in final image)
COPY --from=builder /opt/venv /opt/venv

WORKDIR $APP_HOME

# Copy application code (respects .dockerignore below)
COPY --chown=luxus:luxus backend/ $APP_HOME/

# Drop privileges
USER luxus

EXPOSE 8000

# Basic container-level healthcheck; adjust path to your actual health endpoint
# (add a GET /health route in FastAPI that returns 200 if you don't have one yet).
# Uses Python's stdlib instead of curl, so no extra package needs installing.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

# Assumes your FastAPI instance is `app` inside backend/app/main.py (app.main:app).
# If your entrypoint file/object is named differently, change the module:attr below.
# --workers 2 = 2 uvicorn worker processes; tune to your CPU cores (roughly 2*cores+1).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
