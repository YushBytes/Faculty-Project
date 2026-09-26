"""Import every ORM model here so ``Base.metadata`` is complete for Alembic.

Phase 1 defines no tables yet; module models are registered in later phases.
"""

from app.db.base import Base

__all__ = ["Base"]
