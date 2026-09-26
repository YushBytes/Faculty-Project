from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel


class PageParams(BaseModel):
    limit: int
    offset: int


def page_params(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


T = TypeVar("T")


class Page(BaseModel, Generic[T]):  # noqa: UP046 - PEP 695 syntax needs 3.12; we support 3.11
    items: list[T]
    total: int
    limit: int
    offset: int
