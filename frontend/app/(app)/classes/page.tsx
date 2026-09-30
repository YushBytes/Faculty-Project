"use client";

import { useScope, useWorkspace } from "@/lib/auth/session";
import { PageHead } from "@/components/ui";
import { Sections } from "@/components/sections-table";

export default function Classes() {
  const ws = useWorkspace();
  const scope = useScope();
  return (
    <>
      <PageHead eyebrow="Classes" title={ws.user.role === "FACULTY" ? "My classes" : "Classes"} description="A class is one course taught to one section in one semester. Open a class for its marks, assessments, attention and interventions." />
      <Sections scope={scope} canAssign={ws.capabilities.assign_faculty} />
    </>
  );
}
