FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

# Dependencies first, in their own layer: code changes then rebuild in seconds instead of
# downloading every package again (it matters on slow connections).
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install . \
    && pip uninstall -y acadlytics-backend \
    && rm -rf app build *.egg-info
COPY app ./app
RUN pip install --no-deps .

COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000

# Apply migrations, create the sign-in accounts on an empty database, then serve. Both steps
# are idempotent (no-ops once done).
CMD ["sh", "-c", "alembic upgrade head && python -m app.cli bootstrap && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
