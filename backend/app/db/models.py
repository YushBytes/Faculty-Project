"""Complete model registry for Alembic. Shared file: agents add models to their own
registry (models_platform.py / models_intelligence.py), not here."""

from app.db import models_intelligence, models_platform  # noqa: F401  (registers tables)
from app.db.base import Base

__all__ = ["Base"]
