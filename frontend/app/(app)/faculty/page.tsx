"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { useScope, useUrlState, useWorkspace } from "@/lib/auth/session";
import { periodQuery, useOverview } from "@/components/overview";
import { Badge, BarCell, Card, DataTable, Delta, ErrorState, LoadingDashboard, PageHead } from "@/components/ui";
import { RankBars, Sparkline } from "@/components/charts";
import { num, pctOf } from "@/lib/format";

export default function Faculty() {
  const ws = useWorkspace();
  const scope = useScope();
  const router = useRouter();
  const { set } = useUrlState();
  const [search, setSearch] = useState("");
  const { data, error, loading, reload } = useOverview(scope);
  const rows = useMemo(() => (data?.comparisons.faculty ?? []).filter((r) => r.label.toLowerCase().includes(search.toLowerCase())), [data, search]);
  if (error) return <ErrorState error={error} retry={reload} />;
  if (loading || !data) return <LoadingDashboard />;
  const q = periodQuery(scope);
  const courseQ = scope.course_id ? `&course_id=${scope.course_id}` : "";
  return (
    <>
      <PageHead eyebrow={`${data.scope.root} · ${data.period}`} title="Faculty comparison" description="Results of the classes each faculty member teaches. These are factual measures of student results — sections differ in cohort and timing, so read them alongside the section view." />
      <div className="filters">
        <select className="select" aria-label="Course" value={scope.course_id ?? ""} onChange={(e) => set({ course_id: e.target.value || null })}>
          <option value="">All courses in scope</option>
          {data.comparisons.courses.map((c) => <option key={c.id} value={c.id}>{c.label} {c.name}</option>)}
          {scope.course_id && !data.comparisons.courses.some((c) => c.id === scope.course_id) && <option value={scope.course_id}>Selected course</option>}
        </select>
        <div className="search"><Search size={16} /><input className="input" placeholder="Find faculty" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        {!ws.capabilities.compare_faculty && <Badge>Your own classes only</Badge>}
      </div>
      <div className="grid g-main-r">
        <Card title="Average course score" subtitle="Click a name to open their classes"><div style={{ maxHeight: 720, overflowY: "auto" }}><RankBars rows={rows} href={(r) => `/faculty/${r.id}${q}${courseQ}`} /></div></Card>
        <DataTable rows={rows} rowKey={(r) => r.id} onRowClick={(r) => router.push(`/faculty/${r.id}${q}${courseQ}`)} initialSort={{ key: "avg", dir: "desc" }} maxHeight={740} columns={[
          { key: "label", label: "Faculty", sort: (r) => r.label, render: (r) => <span className="strong">{r.label}<span className="sub">{r.course_codes?.join(", ")}</span></span> },
          { key: "sections", label: "Sections", align: "right", sort: (r) => r.sections, render: (r) => r.sections },
          { key: "students", label: "Students", align: "right", sort: (r) => r.scored, render: (r) => num(r.scored) },
          { key: "avg", label: "Average", sort: (r) => r.average.value, render: (r) => <BarCell v={r.average.value} /> },
          { key: "pass", label: "Pass %", align: "right", sort: (r) => r.pass_percent.value, render: (r) => pctOf(r.pass_percent) },
          { key: "trend", label: "Trend", render: (r) => <Sparkline values={r.trend.map((t) => t.mean)} /> },
          { key: "chg", label: "Latest", align: "right", sort: (r) => r.latest_change, render: (r) => <Delta v={r.latest_change} /> },
          { key: "att", label: "Attention", align: "right", sort: (r) => r.attention_students, render: (r) => <Badge tone="amber">{r.attention_students}</Badge> },
        ]} />
      </div>
    </>
  );
}
