"""The module's API surface: the response models ``/api/v1/analytics/*`` serialises.

Every module in this codebase has a ``schemas.py``, and this is analytics'. It deliberately
**re-exports** the contracts from :mod:`app.modules.analytics.core.outputs` rather than
declaring a parallel set of API models.

A second layer of response schemas would mean every analytics value existed twice, with a
mapping between them that is exactly where a rounded number, a dropped ``n`` or a lost
insufficient-data status goes missing. The core contracts are already pydantic models with
JSON-safe types (``JsonDecimal`` serialises as a number), so FastAPI can return them
directly and the OpenAPI document at ``/docs`` — the published interface — is generated from
the same definitions the formulas produce.

Request-side models (query filters, intervention payloads) do belong here, and are added in
the phase that adds the endpoint that needs them.
"""

from app.modules.analytics.core.contracts import AssessmentRef, ResultStatus, StudentRef
from app.modules.analytics.core.outputs import (
    ANALYTICS_CONTRACTS,
    AssessmentAnalytics,
    AttentionFlag,
    ChangeAnalysis,
    ChangeGroup,
    ClassHealth,
    DataCoverage,
    DistributionBin,
    EvidenceItem,
    Explanation,
    ExtremeScore,
    GeneratedInsight,
    InterventionOutcome,
    OutcomeGroup,
    ScoreDistribution,
    SegmentFactor,
    StudentAssessmentPerformance,
    StudentFinding,
    StudentPerformanceHistory,
    StudentPerformanceProfile,
    StudentSegment,
    StudentTrend,
)
from app.modules.analytics.core.policy import SeriesPoint
from app.modules.analytics.core.results import Label, Measure, MeasureStatus, Unit

__all__ = [
    "ANALYTICS_CONTRACTS",
    "AssessmentAnalytics",
    "AssessmentRef",
    "AttentionFlag",
    "ChangeAnalysis",
    "ChangeGroup",
    "ClassHealth",
    "DataCoverage",
    "DistributionBin",
    "EvidenceItem",
    "Explanation",
    "ExtremeScore",
    "GeneratedInsight",
    "InterventionOutcome",
    "Label",
    "Measure",
    "MeasureStatus",
    "OutcomeGroup",
    "ResultStatus",
    "ScoreDistribution",
    "SegmentFactor",
    "SeriesPoint",
    "StudentAssessmentPerformance",
    "StudentFinding",
    "StudentPerformanceHistory",
    "StudentPerformanceProfile",
    "StudentRef",
    "StudentSegment",
    "StudentTrend",
    "Unit",
]
