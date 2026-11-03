"use client";

import { use } from "react";
import { ScopePage } from "@/components/scope-page";

export default function DepartmentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <ScopePage
      fixed={{ department_id: id }}
      variant="department"
      eyebrow="Department"
      title={(o) => o.comparisons.departments[0]?.name ?? o.scope.crumbs[0]?.label ?? "Department"}
      description={(o) => `${o.counts.courses} courses · ${o.counts.sections} sections · ${o.counts.faculty} faculty · ${o.counts.students.toLocaleString("en-IN")} students`}
    />
  );
}
