"""The results-changed hook (contract C4).

Every write of assessment results (manual PUT, import confirm, deletion, admin rebuild)
calls ``recompute(session, assessment_id)`` *inside the writer's transaction, before it
commits*, so derived analytics (summaries, attention flags) land atomically with the
results that caused them.

The platform ships a no-op. The analytics layer installs the real implementation once,
at import time of its module:

    from app.core.recompute import set_recompute

    def recompute_assessment(session: Session, assessment_id: uuid.UUID) -> None:
        ...  # read via platform services, write derived rows; MUST NOT commit

    set_recompute(recompute_assessment)
"""

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

RecomputeFn = Callable[[Session, uuid.UUID], None]


def _noop(session: Session, assessment_id: uuid.UUID) -> None:
    return None


_impl: RecomputeFn = _noop


def set_recompute(fn: RecomputeFn) -> None:
    global _impl
    _impl = fn


def reset_recompute() -> None:
    set_recompute(_noop)


def recompute(session: Session, assessment_id: uuid.UUID) -> None:
    """Run the installed hook. It must not commit; an exception aborts the whole write."""
    _impl(session, assessment_id)
