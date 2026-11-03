"""The results-changed hook (contract C4).

Every write of assessment results (manual PUT, import confirm, deletion, admin rebuild)
calls ``recompute(session, assessment_id)`` *inside the writer's transaction, before it
commits*, so derived analytics (summaries, attention flags) land atomically with the
results that caused them.

The platform ships a no-op. The analytics layer installs the real implementation once,
at import time of its module:

    from app.core.recompute import install_recompute

    def recompute_assessment(session: Session, assessment_id: uuid.UUID) -> None:
        ...  # read via platform services, write derived rows; MUST NOT commit

    install_recompute(recompute_assessment)

Two tiers, because installing an implementation and borrowing the hook for one test are
different acts that were previously the same call:

``install_recompute(fn)``
    production wiring. ``fn`` becomes both the live hook *and the baseline* that
    :func:`reset_recompute` returns to.

``set_recompute(fn)`` / ``reset_recompute()``
    a temporary replacement and its undo, for tests that need to observe the hook or make
    it fail. ``reset_recompute`` restores the installed implementation — not the no-op —
    so a test that borrows the hook cannot silently disable analytics for everything that
    runs after it. With nothing installed (a pure unit context that never imports the
    analytics module) the baseline is still the no-op, so that behaviour is unchanged.

``reset_recompute`` is idempotent and safe to call when nothing was replaced, which
matters: it is used in fixture teardown that runs whether or not the test installed a spy.
"""

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

RecomputeFn = Callable[[Session, uuid.UUID], None]


def _noop(session: Session, assessment_id: uuid.UUID) -> None:
    return None


_installed: RecomputeFn = _noop
"""The implementation the application wired up: the baseline a reset returns to."""

_impl: RecomputeFn = _noop
"""What ``recompute`` actually calls — the installed implementation, or a test's stand-in."""


def install_recompute(fn: RecomputeFn) -> None:
    """Install the real implementation. Call once, at import time of the analytics module."""
    global _impl, _installed
    _installed = fn
    _impl = fn


def set_recompute(fn: RecomputeFn) -> None:
    """Replace the hook temporarily (tests). Undo with :func:`reset_recompute`.

    Does not change the installed baseline, so the replacement cannot outlive the test that
    made it.
    """
    global _impl
    _impl = fn


def reset_recompute() -> None:
    """Restore the installed implementation, discarding any temporary replacement."""
    global _impl
    _impl = _installed


def recompute(session: Session, assessment_id: uuid.UUID) -> None:
    """Run the installed hook. It must not commit; an exception aborts the whole write."""
    _impl(session, assessment_id)
