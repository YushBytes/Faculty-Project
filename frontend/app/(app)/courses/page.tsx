"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useScope, useWorkspace } from "@/lib/auth/session";
import { periodQuery, useOverview } from "@/components/overview";
import { Badge, BarCell, Card, DataTable, Delta, ErrorState, LoadingDashboard, PageHead } from "@/components/ui";
import { GroupedBars, MultiTrend, Sparkline } from "@/components/charts";
import { num, pctOf } from "@/lib/format";

export default function Courses() {
  const ws = useWorkspace();
  const scope = useScope();
  const router = useRouter();
  const { data, error, loading, reload } = useOverview(scope);
  if (error) return <ErrorState error={error} retry={reload} />;
  if (loading || !data) return <LoadingDashboard />;
  const q = periodQuery(scope);
  const rows = data.comparisons.courses;
  const title = ws.user.role === "COURSE_COORDINATOR" ? "My courses" : ws.user.role === "ACADEMIC_HEAD" ? "Course portfolio" : "Courses";
  return (
    <>
      <PageHead eyebrow={`${data.scope.root} · ${data.period}`} title={title} description={`${rows.length} course${rows.length === 1 ? "" : "s"} in scope. Health, coordinators and movement at a glance — open a course for its sections, faculty and assessments.`} />
      <div className="grid g-2">
        <Card title="Course health" subtitle="Average, pass % and completion per course"><GroupedBars rows={rows} /></Card>
        <Card title="Assessment trend per course" subtitle="Mean % in teaching order"><MultiTrend series={data.course_trends} /></Card>
      </div>
      <div className="section">
        <DataTable
          rows={rows}
          rowKey={(r) => r.id}
          onRowClick={(r) => router.push(`/courses/${r.id}${q}`)}
          initialSort={{ key: "label", dir: "asc" }}
          columns={[
            { key: "label", label: "Course", sort: (r) => r.label, render: (r) => <span className="strong">{r.label} <Badge tone="outline">{r.course_type ?? "—"}</Badge><span className="sub">{r.name}</span></span> },
            { key: "coord", label: "Coordinator", render: (r) => r.coordinators?.length ? r.coordinators.join(", ") : <span className="muted">Unassigned</span> },
            { key: "sections", label: "Sections", align: "right", sort: (r) => r.sections, render: (r) => r.sections },
            { key: "faculty", label: "Faculty", align: "right", sort: (r) => r.faculty ?? 0, render: (r) => r.faculty },
            { key: "students", label: "Students", align: "right", sort: (r) => r.scored, render: (r) => num(r.scored) },
            { key: "avg", label: "Average", sort: (r) => r.average.value, render: (r) => <BarCell v={r.average.value} /> },
            { key: "pass", label: "Pass %", align: "right", sort: (r) => r.pass_percent.value, render: (r) => pctOf(r.pass_percent) },
            { key: "trend", label: "Trend", render: (r) => <Sparkline values={r.trend.map((t) => t.mean)} /> },
            { key: "chg", label: "Latest", align: "right", sort: (r) => r.latest_change, render: (r) => <Delta v={r.latest_change} /> },
            { key: "att", label: "Attention", align: "right", sort: (r) => r.attention_students, render: (r) => <Badge tone="amber">{r.attention_students}</Badge> },
          ]}
        />
      </div>
      {ws.capabilities.manage_coordinators && <p className="muted" style={{ marginTop: 12, fontSize: 13.5 }}>Assign coordinators from a course page or from <Link href="/team" style={{ color: "var(--accent)" }}>Team &amp; roles</Link>.</p>}
    </>
  );
}
