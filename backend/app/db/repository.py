"""Shared repository building blocks."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Generic, TypeVar

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError
from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)

# PostgreSQL SQLSTATE codes
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
CHECK_VIOLATION = "23514"


@contextmanager
def write_guard(
    session: Session,
    *,
    conflict: str = "The record conflicts with an existing one.",
    in_use: str = "The record is referenced by other records.",
    invalid: str = "The record violates a data rule.",
) -> Iterator[None]:
    """Run a write inside a SAVEPOINT and translate constraint violations into API errors.

    Make the change (add / delete / attribute updates) *inside* the block. If the flush
    fails, the SAVEPOINT rollback discards exactly that change and the session stays usable.

        with write_guard(session, conflict="Code already exists."):
            repo.add(Department(...))
    """
    try:
        with session.begin_nested():
            yield
            session.flush()
    except IntegrityError as exc:
        code = getattr(exc.orig, "sqlstate", None)
        if code == UNIQUE_VIOLATION:
            raise ConflictError(conflict) from exc
        if code == FOREIGN_KEY_VIOLATION:
            raise ConflictError(in_use) from exc
        if code == CHECK_VIOLATION:
            raise BusinessRuleError(invalid) from exc
        raise


class BaseRepository(Generic[ModelT]):  # noqa: UP046 - PEP 695 needs 3.12; we support 3.11
    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)

    def page(
        self,
        query: Select[Any],
        *,
        limit: int,
        offset: int,
        order_by: list[Any],
    ) -> tuple[list[Any], int]:
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(query.order_by(*order_by).limit(limit).offset(offset))
        return list(rows.unique().all()), total

    def exists(self, *conditions: ColumnElement[bool]) -> bool:
        return bool(self.session.scalar(select(select(self.model).where(*conditions).exists())))
