"""SRM internal-assessment schemes (regulation 2021), by course type.

The numbers are the component contributions from the institution's scheme sheet. On SRM's
TLP reports a component's "Component Max. Mark" equals its contribution (FP-I: 10.00), so a
component is created with ``max_marks = weightage``. Theory and joint courses total 60
(the end-semester examination supplies the rest); project, practical and non-credit courses
total 100. Non-credit (M) components carry no marks in the scheme, so they are created with
weightage 0 and a nominal maximum of 100, and never contribute to a course score.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.assessments.models import AssessmentType
from app.modules.organization.models import CourseType

Component = tuple[str, AssessmentType, Decimal]

SCHEMES: dict[CourseType, tuple[Component, ...]] = {
    CourseType.THEORY: (
        ("FT-I", AssessmentType.FT, Decimal("5")),
        ("FT-II", AssessmentType.FT, Decimal("15")),
        ("FT-III", AssessmentType.FT, Decimal("15")),
        ("FT-IV", AssessmentType.FT, Decimal("15")),
        ("LLT-I", AssessmentType.LLT, Decimal("10")),
    ),
    CourseType.JOINT: (
        ("FJ-I", AssessmentType.FJ, Decimal("15")),
        ("LLJ-I", AssessmentType.LLJ, Decimal("7")),
        ("FJ-II", AssessmentType.FJ, Decimal("15")),
        ("FJ-III", AssessmentType.FJ, Decimal("15")),
        ("LLJ-II", AssessmentType.LLJ, Decimal("8")),
    ),
    CourseType.PROJECT: (
        ("FP-I", AssessmentType.FP, Decimal("10")),
        ("PBL-I", AssessmentType.PBL, Decimal("20")),
        ("PBL-II", AssessmentType.PBL, Decimal("20")),
        ("FP-II", AssessmentType.FP, Decimal("10")),
        ("PBL-III", AssessmentType.PBL, Decimal("20")),
        ("Report and Viva Voce", AssessmentType.VIVA, Decimal("20")),
    ),
    CourseType.PRACTICAL: (
        ("FL-I", AssessmentType.FL, Decimal("15")),
        ("FL-II", AssessmentType.FL, Decimal("15")),
        ("FL-III", AssessmentType.FL, Decimal("15")),
        ("FL-IV", AssessmentType.FL, Decimal("15")),
        ("Practical Exam", AssessmentType.PRACTICAL, Decimal("40")),
    ),
    CourseType.NON_CREDIT: (
        ("FM-I", AssessmentType.FM, Decimal("0")),
        ("FM-II", AssessmentType.FM, Decimal("0")),
        ("FM-III", AssessmentType.FM, Decimal("0")),
    ),
}

SCHEME_TOTAL = {kind: sum((c[2] for c in comps), Decimal("0")) for kind, comps in SCHEMES.items()}


def component_max(weightage: Decimal) -> Decimal:
    return weightage if weightage > 0 else Decimal("100")
