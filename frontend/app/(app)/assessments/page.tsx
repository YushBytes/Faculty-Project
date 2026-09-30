"use client";

import Link from "next/link";
import { useScope } from "@/lib/auth/session";
import { periodQuery, useOverview } from "@/components/overview";
import { FilterBar } from "@/components/filter-bar";
import { Card, Delta, Empty, ErrorState, LoadingDashboard, PageHead } from "@/components/ui";
import { Heatmap, MultiTrend, TrendChart } from "@/components/charts";
import { pctOf } from "@/lib/format";
import { useRouter } from "next/navigation";

export default function Assessments() {
  const scope = useScope();
  const router = useRouter();
  const { data, error, loading, reload } = useOverview(scope);
  const q = periodQuery(scope);
  const extra = scope.course_id ? `&course_id=${scope.course_id}` : "";
  return (
    <>
      <PageHead eyebrow="Assessments" title="Assessment analytics" description="How each assessment went across the classes in scope: mean, pass rate, completion and the movement from the one before. Choose a course to compare like with like." />
      <FilterBar show={["course", "section"]} />
      {error ? <ErrorState error={error} retry={reload} /> : loading || !data ? <LoadingDashboard /> : data.trend.length === 0 ? <Card><Empty title="No published assessments in this scope yet">Marks appear here once a TLP upload is confirmed and the assessment is published.</Empty></Card> : (
        <>
          <div className="grid g-main">
            <Card title={data.counts.courses > 1 ? "Mean % per course" : "Trend"} subtitle={data.counts.courses > 1 ? "Pick one course above to compare its assessments directly" : "Click a point to open that assessment"}>
              {data.counts.courses > 1 ? <MultiTrend series={data.course_trends} /> : <TrendChart points={data.trend} onSelect={(k) => router.push(`/assessments/${k}${q}${extra}`)} />}
            </Card>
            <Card title="All assessments">
              <div className="list" style={{ maxHeight: 420, overflowY: "auto" }}>{data.trend.map((t) => (
                <Link className="list-item" key={t.key} href={`/assessments/${t.key}${q}${extra}`}>
                  <div className="grow"><b>{t.name}</b><small>{t.offerings} classes · pass {pctOf(t.pass_percent)} · completion {pctOf(t.completion_percent)}</small></div>
                  <b className="tabular">{pctOf(t.mean)}</b><Delta v={t.change} />
                </Link>))}</div>
            </Card>
          </div>
          <Card className="section" title={data.heatmap_rows === "sections" ? "Section × assessment" : "Course × assessment"} subtitle="Mean %"><Heatmap columns={data.heatmap.columns} rows={data.heatmap.rows} max={120} href={(id) => data.heatmap_rows === "sections" ? `/sections/${id}${q}` : `/courses/${id}${q}`} /></Card>
        </>
      )}
    </>
  );
}
