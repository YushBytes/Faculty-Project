"use client";

import { use } from "react";
import { ScopePage } from "@/components/scope-page";

export default function SectionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <ScopePage
      fixed={{ section_id: id }}
      variant="section"
      eyebrow="Section"
      title={(o) => o.scope.crumbs.find((c) => c.kind === "section")?.label ?? "Section"}
      description={(o) => `${o.counts.courses} courses · ${o.counts.faculty} faculty · ${o.counts.students} students`}
    />
  );
}
