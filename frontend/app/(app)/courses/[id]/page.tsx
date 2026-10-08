"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { Network, Upload } from "lucide-react";
import { useScope, useWorkspace } from "@/lib/auth/session";
import { ScopePage } from "@/components/scope-page";
import { OverviewDashboard, periodQuery } from "@/components/overview";
import { Badge, BarCell, Card, DataTable, Delta, Tabs } from "@/components/ui";
import { MatrixLines, RankBars, Sparkline, TrendChart } from "@/components/charts";
import { CoordinatorDrawer } from "@/components/assign";
import { Sections } from "@/components/sections-table";
import { num, pctOf } from "@/lib/format";

type Tab = "overview" | "sections" | "faculty" | "assessments";

export default function CoursePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const ws = useWorkspace();
  const scope = useScope({ course_id: id });
  const [tab, setTab] = useState<Tab>("overview");
  const [coordinators, setCoordinators] = useState(false);
  const [nonce, setNonce] = useState(0);
  return (
    <>
      <ScopePage
        key={nonce}
        fixed={{ course_id: id }}
        variant="course"
        eyebrow="Course"
        title={(o) => o.scope.crumbs.find((c) => c.kind === "course")?.label ?? "Course"}
        description={(o) => {
          const c = o.comparisons.courses[0];
          return `${o.counts.sections} sections · ${o.counts.faculty} faculty · ${o.counts.students.toLocaleString("en-IN")} students${c?.coordinators?.length ? ` · Coordinator: ${c.coordinators.join(", ")}` : ""}`;
        }}
        extra={() => (
          <>
            {ws.capabilities.manage_coordinators && <button className="btn" onClick={() => setCoordinators(true)}><Network size={17} /> Coordinators</button>}
            <Link className="btn btn-primary" href={`/import?course_id=${id}`}><Upload size={17} /> Upload TLP files</Link>
          </>
        )}
        tabs={(o) => (
          <>
            <Tabs tabs={[{ id: "overview", label: "Overview" }, { id: "sections", label: "Sections", count: o.counts.offerings }, { id: "faculty", label: "Faculty", count: o.counts.faculty }, { id: "assessments", label: "Assessments", count: o.trend.length }]} value={tab} onChange={setTab} />
            {tab === "overview" && <OverviewDashboard filters={scope} variant="course" data={o} />}
            {tab === "sections" && <Sections scope={scope} canAssign={ws.capabilities.assign_faculty} onChanged={() => setNonce((n) => n + 1)} />}
            {tab === "faculty" && (
              <div className="grid g-main-r">
                <Card title="Faculty comparison" subtitle="Average course score of the classes each person teaches"><RankBars rows={o.comparisons.faculty} href={(r) => `/faculty/${r.id}${periodQuery(scope)}&course_id=${id}`} /></Card>
                <DataTable rows={o.comparisons.faculty} rowKey={(r) => r.id} initialSort={{ key: "avg", dir: "desc" }} columns={[
                  { key: "label", label: "Faculty", sort: (r) => r.label, render: (r) => <Link className="strong" href={`/faculty/${r.id}${periodQuery(scope)}&course_id=${id}`}>{r.label}</Link> },
                  { key: "sections", label: "Sections", align: "right", sort: (r) => r.sections, render: (r) => r.sections },
                  { key: "students", label: "Students", align: "right", sort: (r) => r.scored, render: (r) => num(r.scored) },
                  { key: "avg", label: "Average", sort: (r) => r.average.value, render: (r) => <BarCell v={r.average.value} /> },
                  { key: "pass", label: "Pass %", align: "right", sort: (r) => r.pass_percent.value, render: (r) => pctOf(r.pass_percent) },
                  { key: "trend", label: "Trend", render: (r) => <Sparkline values={r.trend.map((t) => t.mean)} /> },
                  { key: "att", label: "Attention", align: "right", sort: (r) => r.attention_students, render: (r) => <Badge tone="amber">{r.attention_students}</Badge> },
                ]} />
              </div>
            )}
            {tab === "assessments" && (
              <div className="grid g-main">
                <Card title="Assessment trend" subtitle="Click a point to compare that assessment across sections"><TrendLinkCourse id={id} scopeQuery={periodQuery(scope)} points={o.trend} /></Card>
                <Card title="Assessments">
                  <div className="list">{o.trend.map((t) => (
                    <Link className="list-item" key={t.key} href={`/assessments/${t.key}${periodQuery(scope)}&course_id=${id}`}>
                      <div className="grow"><b>{t.name}</b><small>max {t.max_marks?.join(", ")} · {t.offerings} sections · pass {pctOf(t.pass_percent)}</small></div>
                      <b className="tabular">{pctOf(t.mean)}</b><Delta v={t.change} />
                    </Link>))}
                  </div>
                </Card>
                <Card title="Section trend across assessments" className="section" subtitle="Mean % per assessment"><MatrixLines columns={o.assessment_matrix.columns} rows={o.assessment_matrix.rows} /></Card>
              </div>
            )}
          </>
        )}
      />
      {coordinators && <CoordinatorDrawer courseId={id} onClose={() => setCoordinators(false)} onChanged={() => setNonce((n) => n + 1)} />}
    </>
  );
}

function TrendLinkCourse({ id, scopeQuery, points }: { id: string; scopeQuery: string; points: Parameters<typeof TrendChart>[0]["points"] }) {
  const router = useRouter();
  return <TrendChart points={points} onSelect={(key) => router.push(`/assessments/${key}${scopeQuery}&course_id=${id}`)} />;
}

