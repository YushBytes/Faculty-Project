"use client";

import { useScope, useWorkspace } from "@/lib/auth/session";
import { OverviewDashboard } from "@/components/overview";
import { FilterBar } from "@/components/filter-bar";
import { PageHead } from "@/components/ui";
import { HowItWorks } from "@/components/how-it-works";

export default function Analytics() {
  const ws = useWorkspace();
  const scope = useScope();
  const variant = scope.faculty_id ? "faculty" : scope.section_id ? "section" : scope.course_id ? "course" : ({ ADMIN: "institution", HOD: "department", ACADEMIC_HEAD: "portfolio", COURSE_COORDINATOR: "coordinator", FACULTY: "teacher" } as const)[ws.user.role];
  return (
    <>
      <PageHead eyebrow="Analytics" title="Performance analytics" description="Understand class and student performance: trends, distributions, comparisons and attention for any slice of your scope. The same engine computes every level — only the scope changes." />
      <HowItWorks>
        <p>Every figure comes from confirmed, published marks. Percentages are mark ÷ maximum; class averages use each student&apos;s weighted course score; pass rate is over students who have a result, and absence is reported separately as completion.</p>
        <p>Where there are too few students or assessments for a figure to mean anything, it shows “—” with the reason instead of a guess. Nothing here predicts results.</p>
        <p>Next step: narrow the scope with the filters, then open a course, section or class to drill down.</p>
      </HowItWorks>
      <FilterBar show={["department", "course", "section", "faculty"]} />
      <OverviewDashboard filters={scope} variant={variant} />
    </>
  );
}
