"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { useScope } from "@/lib/auth/session";
import { periodQuery, useOverview } from "@/components/overview";
import { Badge, BarCell, Card, DataTable, Delta, ErrorState, LoadingDashboard, PageHead } from "@/components/ui";
import { HeatScale, Sparkline } from "@/components/charts";
import { num, pct, pctOf, scaleColor } from "@/lib/format";

export default function Sections() {
  const scope = useScope();
  const router = useRouter();
  const [search, setSearch] = useState("");
  const { data, error, loading, reload } = useOverview(scope);
  const rows = useMemo(() => (data?.comparisons.sections ?? []).filter((r) => r.label.toLowerCase().includes(search.toLowerCase())), [data, search]);
  if (error) return <ErrorState error={error} retry={reload} />;
  if (loading || !data) return <LoadingDashboard />;
  const q = periodQuery(scope);
  const all = data.comparisons.sections;
  const ranked = all.filter((r) => r.average.value !== null).sort((a, b) => (b.average.value ?? 0) - (a.average.value ?? 0));
  return (
    <>
      <PageHead eyebrow={`${data.scope.root} · ${data.period}`} title={`${all.length} sections`} description="Every section in scope, pooled across its courses. Colour shows the average course score; open a section for its courses, faculty and students." />
      <div className="kpis" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))" }}>
        <div className="kpi"><div className="k-label">Highest average</div><div className="k-value">{ranked[0] ? pct(ranked[0].average.value) : "—"}</div><div className="k-foot">{ranked[0]?.label}</div></div>
        <div className="kpi"><div className="k-label">Lowest average</div><div className="k-value">{ranked.at(-1) ? pct(ranked.at(-1)!.average.value) : "—"}</div><div className="k-foot">{ranked.at(-1)?.label}</div></div>
        <div className="kpi"><div className="k-label">Sections below 55%</div><div className="k-value">{ranked.filter((r) => (r.average.value ?? 100) < 55).length}</div><div className="k-foot">of {all.length}</div></div>
        <div className="kpi warn"><div className="k-label">Students needing attention</div><div className="k-value">{num(data.kpis.attention_students)}</div><div className="k-foot">across all sections</div></div>
      </div>
      <Card className="section" title="Section map" subtitle="Each tile is a section; hover for pass % and attention">
        <div className="tile-grid">
          {all.map((r) => (
            <Link key={r.id} className="tile" href={`/sections/${r.id}${q}`} style={{ background: scaleColor(r.average.value) }} title={`${r.label}: average ${pctOf(r.average)}, pass ${pctOf(r.pass_percent)}, ${r.attention_students} need attention`}>
              <b>{r.label}</b><span>{pctOf(r.average)} · {r.attention_students}⚑</span>
            </Link>
          ))}
        </div>
        <HeatScale />
      </Card>
      <div className="section">
        <div className="filters"><div className="search"><Search size={16} /><input className="input" placeholder="Find a section (e.g. B4)" value={search} onChange={(e) => setSearch(e.target.value)} /></div></div>
        <DataTable rows={rows} rowKey={(r) => r.id} onRowClick={(r) => router.push(`/sections/${r.id}${q}`)} initialSort={{ key: "avg", dir: "asc" }} maxHeight={640} columns={[
          { key: "label", label: "Section", sort: (r) => r.label, render: (r) => <span className="strong">{r.label}<span className="sub">Batch {r.batch_year}</span></span> },
          { key: "courses", label: "Courses", align: "right", render: (r) => r.courses },
          { key: "students", label: "Enrolments", align: "right", sort: (r) => r.enrolments, render: (r) => num(r.enrolments) },
          { key: "avg", label: "Average", sort: (r) => r.average.value, render: (r) => <BarCell v={r.average.value} /> },
          { key: "median", label: "Median", align: "right", sort: (r) => r.median.value, render: (r) => pctOf(r.median) },
          { key: "pass", label: "Pass %", align: "right", sort: (r) => r.pass_percent.value, render: (r) => pctOf(r.pass_percent) },
          { key: "fail", label: "Below pass", align: "right", sort: (r) => r.fail_percent.value, render: (r) => pctOf(r.fail_percent) },
          { key: "comp", label: "Completion", align: "right", sort: (r) => r.completion_percent.value, render: (r) => pctOf(r.completion_percent) },
          { key: "trend", label: "Trend", render: (r) => <Sparkline values={r.trend.map((t) => t.mean)} /> },
          { key: "chg", label: "Latest", align: "right", sort: (r) => r.latest_change, render: (r) => <Delta v={r.latest_change} /> },
          { key: "att", label: "Attention", align: "right", sort: (r) => r.attention_students, render: (r) => <Badge tone="amber">{r.attention_students}</Badge> },
        ]} />
      </div>
    </>
  );
}
