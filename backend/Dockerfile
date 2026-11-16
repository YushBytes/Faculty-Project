FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

# Dependencies first, in their own layer: code changes then rebuild in seconds instead of
# downloading every package again (it matters on slow connections). constraints.txt pins every
# package to the version the test suite ran against, so the image is reproducible and pip does
# not backtrack through dozens of releases.
COPY pyproject.toml constraints.txt ./
RUN pip install "setuptools>=69" \
    && mkdir app && touch app/__init__.py \
    && pip install -c constraints.txt . \
    && pip uninstall -y acadlytics-backend \
    && rm -rf app build *.egg-info
COPY app ./app
# The build backend is already installed above, so a code-only rebuild needs no network
# (build isolation would download setuptools again on every change).
RUN pip install --no-deps --no-build-isolation .

COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000

# Apply migrations, create the sign-in accounts on an empty database, then serve. Both steps
# are idempotent (no-ops once done). `exec` makes uvicorn PID 1, so `docker stop` (SIGTERM)
# reaches it and it shuts down gracefully instead of being killed after the timeout.
CMD ["sh", "-c", "alembic upgrade head && python -m app.cli bootstrap && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
