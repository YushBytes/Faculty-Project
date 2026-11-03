"use client";

import Link from "next/link";
import { use, useState } from "react";
import { HeartHandshake, TrendingDown, TrendingUp, Minus } from "lucide-react";
import { insightsApi, type StudentOverview } from "@/lib/api/endpoints";
import { useApi } from "@/lib/hooks/use-api";
import { Badge, Card, Empty, ErrorState, Kpi, LoadingDashboard, PageHead, SeverityBadge } from "@/components/ui";
import { StudentLine } from "@/components/charts";
import { InterventionDrawer } from "@/components/intervention-drawer";
import { RULES, SEGMENTS, pct } from "@/lib/format";

type Cls = StudentOverview["classes"][number];

export default function StudentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, loading, reload } = useApi(() => insightsApi.student(id), [id]);
  const [intervene, setIntervene] = useState<Cls | null>(null);
  if (error) return <ErrorState error={error} retry={reload} />;
  if (loading || !data) return <LoadingDashboard />;
  const s = data.student;
  const scored = data.classes.map((c) => c.analytics?.profile.history.weighted_course_score.value).filter((v): v is number => v !== null && v !== undefined);
  const flags = data.classes.reduce((n, c) => n + (c.analytics?.attention?.flags.length ?? 0), 0);
  return (
    <>
      <PageHead crumbs={[{ href: "/students", label: "Students" }, { label: s.full_name }]} eyebrow={`Student · ${s.register_number}`} title={s.full_name}
        description={<>Section {s.section ?? "—"} · batch {s.batch_year}{s.email ? ` · ${s.email}` : ""}{!s.is_active && " · inactive record"}</>} />
      <div className="kpis" style={{ gridTemplateColumns: "repeat(3, minmax(0,1fr))" }}>
        <Kpi label="Classes you can see" value={data.classes.length} />
        <Kpi label="Average course score" tone="accent" value={scored.length ? pct(scored.reduce((a, b) => a + b, 0) / scored.length) : "—"} foot="mean of this student's course scores" />
        <Kpi label="Attention flags" tone="warn" value={flags} foot="live, across classes" />
      </div>
      {data.classes.length === 0 && <Card className="section"><Empty title="No classes of this student are in your scope" /></Card>}
      {data.classes.map((c) => <ClassBlock key={c.offering_id} c={c} onIntervene={() => setIntervene(c)} />)}
      {intervene && <InterventionDrawer offeringId={intervene.offering_id} label={`${intervene.course_code} · ${intervene.section_name}`} preselect={[s.id]} onClose={() => setIntervene(null)} onSaved={reload} />}
    </>
  );
}

function ClassBlock({ c, onIntervene }: { c: Cls; onIntervene: () => void }) {
  const a = c.analytics;
  const h = a?.profile.history;
  const trend = h?.trend.label.value;
  const TrendIcon = trend === "improving" ? TrendingUp : trend === "declining" ? TrendingDown : Minus;
  const points = (h?.points ?? []).map((p) => ({ name: p.assessment_code, pct: p.percentage, state: p.state }));
  return (
    <Card className="section" title={<Link href={`/classes/${c.offering_id}`}>{c.course_code} · {c.course_name}</Link>} subtitle={`Section ${c.section_name} · ${c.term_name}${c.enrollment !== "ACTIVE" ? " · dropped" : ""}`}
      actions={<button className="btn btn-sm" onClick={onIntervene}><HeartHandshake size={15} /> Intervention</button>}>
      {!a ? <Empty title="No analytics for this enrolment">Dropped students keep their marks but are not part of the class cohort.</Empty> : (
        <div className="grid g-main">
          <div>
            <StudentLine points={points} passMark={c.pass_mark} />
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
              {h!.points.filter((p) => p.state !== "assessed").map((p) => <Badge key={p.assessment_id} tone={p.state === "absent" ? "amber" : p.state === "exempt" ? "blue" : undefined}>{p.assessment_code}: {p.state}</Badge>)}
            </div>
          </div>
          <div>
            <div className="list">
              <div className="list-item"><div className="grow"><b>Weighted course score</b><small>{h!.weighted_course_score.reason ?? "over assessments sat"}</small></div><b className="tabular" style={{ fontSize: 20 }}>{pct(h!.weighted_course_score.value)}</b></div>
              <div className="list-item"><div className="grow"><b>Trend</b><small>{h!.trend.label.reason ?? "fitted over the assessments sat"}</small></div><Badge tone={trend === "improving" ? "green" : trend === "declining" ? "red" : undefined}><TrendIcon size={13} /> {trend ?? "insufficient data"}</Badge></div>
              <div className="list-item"><div className="grow"><b>Segment</b></div><Badge tone="violet">{SEGMENTS[a.segment.primary.value ?? ""] ?? "—"}</Badge></div>
              <div className="list-item"><div className="grow"><b>Completion</b></div><b className="tabular">{pct(h!.completion_percent.value)}</b></div>
            </div>
            {a.attention?.flags.length ? (
              <div style={{ marginTop: 12, display: "grid", gap: 8 }}>{a.attention.flags.map((f) => <div key={f.rule_code} className="notice notice-warn"><div><SeverityBadge severity={f.severity} /> <b>{RULES[f.rule_code]?.name}</b><p style={{ marginTop: 4, fontSize: 13.5 }}>{f.message}</p></div></div>)}</div>
            ) : <p className="muted" style={{ marginTop: 12 }}>No attention flags in this class.</p>}
          </div>
          {a.insights.length > 0 && <div style={{ gridColumn: "1 / -1" }}>{a.insights.slice(0, 4).map((i) => <div className="statement" key={i.code + i.text}>•<span>{i.text}</span></div>)}</div>}
        </div>
      )}
    </Card>
  );
}
