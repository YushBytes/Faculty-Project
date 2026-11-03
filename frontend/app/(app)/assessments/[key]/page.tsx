"use client";

import Link from "next/link";
import { use } from "react";
import { useRouter } from "next/navigation";
import { insightsApi } from "@/lib/api/endpoints";
import { useScope } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { periodQuery } from "@/components/overview";
import { BarCell, Card, DataTable, Delta, ErrorState, Kpi, LoadingDashboard, MeasureValue, PageHead } from "@/components/ui";
import { Histogram, RankBars } from "@/components/charts";
import { num, pct, pctOf } from "@/lib/format";

export default function AssessmentPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = use(params);
  const scope = useScope();
  const router = useRouter();
  const { data, error, loading, reload } = useApi(() => insightsApi.assessment(key, scope), [key, scope]);
  if (error) return <ErrorState error={error} retry={reload} />;
  if (loading || !data) return <LoadingDashboard />;
  const a = data.assessment;
  const q = periodQuery(scope);
  const cov = a.coverage ?? {};
  const sectionRows = data.sections.map((s) => ({ id: s.offering_id, label: s.label, average: { value: s.mean.value, status: "ok" as const, n: 0, reason: null }, pass_percent: { value: s.pass_percent.value, status: "ok" as const, n: 0, reason: null } }));
  return (
    <>
      <PageHead crumbs={[{ href: `/assessments${q}`, label: "Assessments" }, { label: a.name }]} eyebrow={`Assessment · ${data.period}`} title={a.name} description={`${a.offerings} classes · maximum ${a.max_marks?.join(" / ")} marks${data.previous ? ` · compared with ${data.previous.name}` : ""}`} />
      <div className="kpis">
        <Kpi label="Mean" tone="accent" value={<MeasureValue m={a.mean} />} foot={<>{a.change !== null ? <Delta v={a.change} /> : "first assessment"}{data.previous && <> vs {data.previous.name} ({pctOf(data.previous.mean)})</>}</>} />
        <Kpi label="Median" value={<MeasureValue m={a.median} />} foot={a.std_dev?.value !== null && a.std_dev ? `σ ${a.std_dev.value?.toFixed(1)} pp` : ""} />
        <Kpi label="Pass %" value={<MeasureValue m={a.pass_percent} />} foot={`${num(a.mean.n)} assessed`} />
        <Kpi label="Below pass" value={pct(a.pass_percent?.value !== null && a.pass_percent ? 100 - (a.pass_percent.value ?? 0) : null)} foot="of those assessed" />
        <Kpi label="Completion" value={<MeasureValue m={a.completion_percent ?? null} />} foot={`${cov.absent ?? 0} absent · ${cov.missing ?? 0} missing`} />
        <Kpi label="Exempt" value={num(cov.exempt ?? 0)} foot="excluded from the denominator" />
      </div>
      <div className="grid g-2 section">
        <Card title="Distribution" subtitle="Percentage of every assessed student, 10-point bins"><Histogram bins={a.distribution ?? []} /></Card>
        <Card title="Section comparison" subtitle="Mean % per class — click to open"><div style={{ maxHeight: 520, overflowY: "auto" }}><RankBars rows={sectionRows as never} href={(r) => `/classes/${r.id}${q}`} /></div></Card>
      </div>
      <div className="section">
        <DataTable rows={data.sections} rowKey={(s) => s.offering_id} onRowClick={(s) => router.push(`/classes/${s.offering_id}${q}`)} initialSort={{ key: "mean", dir: "asc" }} maxHeight={600} columns={[
          { key: "label", label: "Class", sort: (s) => s.label, render: (s) => <span className="strong">{s.label}<span className="sub">{s.faculty.join(", ")}</span></span> },
          { key: "mean", label: "Mean", sort: (s) => s.mean.value, render: (s) => <BarCell v={s.mean.value} /> },
          { key: "median", label: "Median", align: "right", sort: (s) => s.median.value, render: (s) => pct(s.median.value) },
          { key: "pass", label: "Pass %", align: "right", sort: (s) => s.pass_percent.value, render: (s) => pct(s.pass_percent.value) },
          { key: "comp", label: "Completion", align: "right", sort: (s) => s.completion_percent.value, render: (s) => pct(s.completion_percent.value) },
          { key: "abs", label: "Absent", align: "right", sort: (s) => s.coverage.absent, render: (s) => s.coverage.absent },
        ]} />
      </div>
      {data.faculty.length > 1 && (
        <Card className="section" title="Faculty on this assessment" subtitle="Pooled over the classes each person teaches">
          <RankBars rows={data.faculty} href={(r) => `/faculty/${r.id}${q}`} />
        </Card>
      )}
      <p className="muted" style={{ marginTop: 12, fontSize: 13.5 }}>Open a class to see the marks behind these numbers. <Link href={`/import${q}`} style={{ color: "var(--accent)" }}>Upload marks</Link> for classes that are still missing this assessment.</p>
    </>
  );
}
