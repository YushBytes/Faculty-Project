"use client";

import { use } from "react";
import { ScopePage } from "@/components/scope-page";

export default function FacultyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <ScopePage
      fixed={{ faculty_id: id }}
      variant="faculty"
      eyebrow="Faculty"
      title={(o) => o.scope.crumbs.find((c) => c.kind === "faculty")?.label ?? "Faculty"}
      description={(o) => `${o.counts.offerings} classes · ${o.counts.courses} course${o.counts.courses === 1 ? "" : "s"} · ${o.counts.students} students`}
    />
  );
}
