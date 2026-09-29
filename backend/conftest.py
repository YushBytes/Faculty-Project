"""Pytest bootstrap: export this directory's .env before the suite reads the environment.

`tests/conftest.py` resolves `TEST_DATABASE_URL` from `os.environ`, but the application
reads the same `.env` through pydantic-settings, which loads it into `Settings` only and
never exports it into `os.environ`. Without this bootstrap a bare `pytest` falls back to
the hardcoded default in `tests/conftest.py` instead of the port configured in `.env`.

pytest imports the rootdir conftest before `tests/conftest.py`, so this runs first.
Variables already set in the shell (or by CI) win: nothing here overrides them, and a
missing `.env` is a no-op, so the hardcoded defaults still apply.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=False)
