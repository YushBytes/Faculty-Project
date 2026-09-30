"use client";

import { useRouter } from "next/navigation";
import { useScope } from "@/lib/auth/session";
import { useOverview, periodQuery } from "@/components/overview";
import { BarCell, Card, DataTable, ErrorState, LoadingDashboard, PageHead, Badge } from "@/components/ui";
import { GroupedBars } from "@/components/charts";
import { num, pctOf } from "@/lib/format";

export default function Departments() {
  const scope = useScope();
  const router = useRouter();
  const { data, error, loading, reload } = useOverview(scope);
  if (error) return <ErrorState error={error} retry={reload} />;
  if (loading || !data) return <LoadingDashboard />;
  const rows = data.comparisons.departments;
  return (
    <>
      <PageHead eyebrow={`Institution · ${data.period}`} title="Departments" description="Every department's results in the selected period. Open one to drill down to its courses, sections, faculty and students." />
      {rows.length > 1 && <Card title="Department comparison"><GroupedBars rows={rows} /></Card>}
      <div className="section">
        <DataTable
          rows={rows}
          rowKey={(r) => r.id}
          onRowClick={(r) => router.push(`/departments/${r.id}${periodQuery(scope)}`)}
          columns={[
            { key: "label", label: "Department", sort: (r) => r.label, render: (r) => <span className="strong">{r.label}<span className="sub">{r.name}</span></span> },
            { key: "courses", label: "Courses", align: "right", render: (r) => r.courses },
            { key: "sections", label: "Sections", align: "right", render: (r) => r.sections },
            { key: "scored", label: "Students scored", align: "right", render: (r) => num(r.scored) },
            { key: "avg", label: "Average", sort: (r) => r.average.value, render: (r) => <BarCell v={r.average.value} /> },
            { key: "pass", label: "Pass %", align: "right", render: (r) => pctOf(r.pass_percent) },
            { key: "att", label: "Attention", align: "right", render: (r) => <Badge tone="amber">{r.attention_students}</Badge> },
          ]}
        />
      </div>
      <p className="muted" style={{ marginTop: 12, fontSize: 13.5 }}>New departments are created under Academic structure.</p>
    </>
  );
}
