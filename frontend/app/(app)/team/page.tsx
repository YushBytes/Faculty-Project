"use client";

import Link from "next/link";
import { useState } from "react";
import { Network } from "lucide-react";
import { useScope, useWorkspace } from "@/lib/auth/session";
import { periodQuery, useOverview } from "@/components/overview";
import { CoordinatorDrawer } from "@/components/assign";
import { Badge, BarCell, Card, DataTable, ErrorState, LoadingDashboard, PageHead } from "@/components/ui";
import { num, pctOf } from "@/lib/format";

export default function Team() {
  const ws = useWorkspace();
  const scope = useScope();
  const [course, setCourse] = useState<string | null>(null);
  const { data, error, loading, reload } = useOverview(scope);
  if (error) return <ErrorState error={error} retry={reload} />;
  if (loading || !data) return <LoadingDashboard />;
  const q = periodQuery(scope);
  const unassigned = data.comparisons.courses.filter((c) => !c.coordinators?.length);
  return (
    <>
      <PageHead eyebrow={`${data.scope.root} · ${data.period}`} title={ws.user.role === "ACADEMIC_HEAD" ? "Course coordinators" : "Team & roles"} description="Who owns each course, how their courses are doing and how much activity is flowing through them. Changing a coordinator changes who can manage the course from now on — never the marks already recorded." />
      <div className="kpis" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))" }}>
        <div className="kpi"><div className="k-label">Courses</div><div className="k-value">{data.counts.courses}</div></div>
        <div className="kpi"><div className="k-label">Coordinators</div><div className="k-value">{data.counts.coordinators}</div></div>
        <div className="kpi"><div className="k-label">Faculty teaching</div><div className="k-value">{data.counts.faculty}</div></div>
        <div className={`kpi ${unassigned.length ? "warn" : ""}`}><div className="k-label">Courses without a coordinator</div><div className="k-value">{unassigned.length}</div></div>
      </div>
      <Card className="section" title="Coordinator portfolio" subtitle="One row per course">
        <DataTable rows={data.comparisons.courses} rowKey={(r) => r.id} columns={[
          { key: "course", label: "Course", sort: (r) => r.label, render: (r) => <Link className="strong" href={`/courses/${r.id}${q}`}>{r.label}<span className="sub">{r.name}</span></Link> },
          { key: "coord", label: "Coordinator", render: (r) => r.coordinators?.length ? r.coordinators.join(", ") : <Badge tone="amber">Unassigned</Badge> },
          { key: "sections", label: "Sections", align: "right", sort: (r) => r.sections, render: (r) => r.sections },
          { key: "faculty", label: "Faculty", align: "right", sort: (r) => r.faculty ?? 0, render: (r) => r.faculty },
          { key: "students", label: "Students", align: "right", sort: (r) => r.scored, render: (r) => num(r.scored) },
          { key: "avg", label: "Course health", sort: (r) => r.average.value, render: (r) => <BarCell v={r.average.value} /> },
          { key: "pass", label: "Pass %", align: "right", sort: (r) => r.pass_percent.value, render: (r) => pctOf(r.pass_percent) },
          { key: "att", label: "Attention", align: "right", sort: (r) => r.attention_students, render: (r) => <Badge tone="amber">{r.attention_students}</Badge> },
          ...(ws.capabilities.manage_coordinators ? [{ key: "act", label: "", render: (r: (typeof data.comparisons.courses)[number]) => <button className="btn btn-sm" onClick={() => setCourse(r.id)}><Network size={14} /> Assign</button> }] : []),
        ]} />
      </Card>
      <Card className="section" title="Recent activity" subtitle="Imports confirmed in this scope">
        <div className="list">{data.activity.imports.map((i) => <div className="list-item" key={i.id}><div className="grow"><b>{i.file_name}</b><small>{i.offering} · {i.by}</small></div><Badge tone={i.status === "committed" ? "green" : "amber"}>{i.status}</Badge></div>)}</div>
      </Card>
      {course && <CoordinatorDrawer courseId={course} onClose={() => setCourse(null)} onChanged={reload} />}
    </>
  );
}
