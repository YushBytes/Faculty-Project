"use client";

import Link from "next/link";
import { useScope, useWorkspace } from "@/lib/auth/session";
import { Empty, PageHead } from "@/components/ui";
import { Sections } from "@/components/sections-table";

export default function Classes() {
  const ws = useWorkspace();
  const scope = useScope();
  const faculty = ws.user.role === "FACULTY";
  const empty = faculty ? (
    <Empty title="No classes assigned to you in this period">
      Your assigned classes will appear here when they are assigned to you — by your HOD or course coordinator, or when a TLP report naming you is confirmed. If you expected classes, try another academic year or semester at the top of the page.
    </Empty>
  ) : (
    <Empty title="No classes in this view">
      A class appears once a course is taught to a section in a semester{ws.capabilities.import_marks ? <> — usually created by <Link href="/import" style={{ color: "var(--accent)" }}>importing TLP reports</Link></> : null}. Try another academic year or semester at the top of the page.
    </Empty>
  );
  return (
    <>
      <PageHead eyebrow="Classes" title={faculty ? "My classes" : "Classes"} description="A class is one course taught to one section in one semester. Open a class for its marks, assessments, attention and interventions." />
      <Sections scope={scope} canAssign={ws.capabilities.assign_faculty} empty={empty} />
    </>
  );
}
