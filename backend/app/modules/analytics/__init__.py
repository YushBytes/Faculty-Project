"""Analytics: deterministic, explainable academic intelligence over assessment-level data.

Layering inside this module::

    router.py   -> service.py -> repository.py      (Phase 4)
                       |
                       v
                    core/                           pure functions, no I/O
                       |
                       v
                  core/outputs.py                   the eleven response contracts

``core`` is database-independent by construction: it imports no session, no ORM model and
no SQLAlchemy. It consumes the typed contracts in ``core.contracts``, which a later phase
populates from the platform's own services/repositories through the ``SnapshotSource`` port
in ``services.py``. That keeps every formula unit testable against hand-computed fixtures
and keeps faculty scope and PII rules enforced in one place (the platform services), not
duplicated here.

What is in place after Phase 3
------------------------------

``core/contracts.py``   inputs: ``OfferingSnapshot`` and the refs it holds
``core/policy.py``      the missing-data policy and ``StudentSeries``
``core/thresholds.py``  contract C5: every configurable threshold and its provenance
``core/rules.py``       contract C9: the frozen R1-R7 attention-rule registry
``core/results.py``     contract C10: ``Measure``/``Label``, including insufficient data
``core/vocabulary.py``  every categorical label and the set it came from
``core/outputs.py``     the eleven analytics contracts and their explainability payload
``core/statistics.py``  F1, F3-F7: mean, median, population sd, min/max, pass %, completion %
``core/distribution.py`` F8: the ten-bin histogram
``core/student.py``     F2, F7, F10-F13: course score, completion, consistency, decline
``core/trends.py``      F9: slope, method and classification
``core/profile.py``     composition: one student, read as a whole (contract 12)
``config.py``           the system-default threshold layer, from settings
``schemas.py``          the API surface (re-exports the contracts; no second copy)
``services.py``         the ``SnapshotSource`` and ``RecomputeHook`` ports
``repository.py``       the platform's stored data, mapped onto ``OfferingSnapshot``

Still to come, each a pure function set over a snapshot returning the contracts above:
``segmentation``, ``attention`` (the R1-R7 engine), ``class_health``, ``comparison`` ("what
changed"), ``interventions`` (observed outcome) and ``insights`` (deterministic templates).
They are listed in docs/ANALYTICS_SPEC.md with the formula each will implement; none is
stubbed, because an empty module that returns a plausible value is indistinguishable from a
working one.

Scope limits that are part of the design, not omissions:

* Assessment-level data only. There is no question-level or topic-level data in this
  system, so no analytic may depend on one. See docs/PROJECT_CONTEXT.md section 3.
* No prediction, no risk score, no ML. Every output carries the value, the threshold, the
  rule and the sample size that produced it.
* Absent, exempt and missing are never zero. See ``core.policy``.
"""
