"use client";

import Link from "next/link";
import { FileBarChart, Upload } from "lucide-react";
import { useScope, useWorkspace } from "@/lib/auth/session";
import { OverviewDashboard, periodQuery, type Variant } from "@/components/overview";
import { PageHead } from "@/components/ui";
import { semesterLabel } from "@/lib/format";

const VARIANT: Record<string, Variant> = {
  ADMIN: "institution",
  HOD: "department",
  ACADEMIC_HEAD: "portfolio",
  COURSE_COORDINATOR: "coordinator",
  FACULTY: "teacher",
};

export default function Dashboard() {
  const ws = useWorkspace();
  const scope = useScope();
  const role = ws.user.role;
  const first = ws.user.full_name.replace(/^(Dr|Mr|Ms|Mrs|Prof)\.?\s+/i, "");
  const question = {
    ADMIN: "What is happening across the institution?",
    HOD: `What is happening across ${ws.department?.name ?? "the department"}?`,
    ACADEMIC_HEAD: "What is happening across our courses and coordinators?",
    COURSE_COORDINATOR: `What is happening across ${ws.coordinated_courses.map((c) => c.code).join(", ") || "my courses"}, every section and faculty member?`,
    FACULTY: "What is happening in my classes and with my students?",
  }[role];
  return (
    <>
      <PageHead
        eyebrow={scope.academic_year ? `${ws.headline} · ${semesterLabel(scope.semester)} · AY ${scope.academic_year}` : ws.headline}
        title={`Welcome back, ${first}.`}
        description={question}
        actions={<>
          <Link className="btn" href={`/reports${periodQuery(scope)}`}><FileBarChart size={17} /> Report</Link>
          <Link className="btn btn-primary" href="/import"><Upload size={17} /> Import TLP marks</Link>
        </>}
      />
      <OverviewDashboard filters={scope} variant={VARIANT[role]} />
    </>
  );
}
