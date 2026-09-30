"use client";

import { useScope, useWorkspace } from "@/lib/auth/session";
import { OverviewDashboard } from "@/components/overview";
import { FilterBar } from "@/components/filter-bar";
import { PageHead } from "@/components/ui";

export default function Analytics() {
  const ws = useWorkspace();
  const scope = useScope();
  const variant = scope.faculty_id ? "faculty" : scope.section_id ? "section" : scope.course_id ? "course" : ({ ADMIN: "institution", HOD: "department", ACADEMIC_HEAD: "portfolio", COURSE_COORDINATOR: "coordinator", FACULTY: "teacher" } as const)[ws.user.role];
  return (
    <>
      <PageHead eyebrow="Analytics" title="Performance analytics" description="Trends, distributions, comparisons and attention for any slice of your scope. The same engine computes every level — only the scope changes." />
      <FilterBar show={["department", "course", "section", "faculty"]} />
      <OverviewDashboard filters={scope} variant={variant} />
    </>
  );
}
