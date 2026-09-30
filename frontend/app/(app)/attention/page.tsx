"use client";

import Link from "next/link";
import { useState } from "react";
import { HeartHandshake } from "lucide-react";
import { insightsApi } from "@/lib/api/endpoints";
import type { AttentionItem } from "@/lib/api/types";
import { useScope, useUrlState } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { periodQuery, useOverview } from "@/components/overview";
import { FilterBar } from "@/components/filter-bar";
import { Card, DataTable, Empty, ErrorState, Kpi, LoadingBlock, PageHead, SeverityBadge } from "@/components/ui";
import { RuleBars } from "@/components/charts";
import { InterventionDrawer } from "@/components/intervention-drawer";
import { RULES, date, num } from "@/lib/format";

const PAGE = 50;

export default function Attention() {
  const scope = useScope();
  const { params, set } = useUrlState();
  const rule = params.get("rule") ?? "";
  const severity = params.get("severity") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const overview = useOverview(scope);
  const { data, error, loading, reload } = useApi(() => insightsApi.attention(scope, { rule: rule || undefined, severity: severity || undefined, limit: PAGE, offset }), [scope, rule, severity, offset]);
  const [intervene, setIntervene] = useState<AttentionItem | null>(null);
  const q = periodQuery(scope);
  const matrix = overview.data?.attention_matrix;
  return (
    <>
      <PageHead eyebrow="Attention" title="Students needing attention" description="Seven deterministic rules on recorded marks. Each flag shows the evidence that fired it — there is no hidden risk score, and a flag is a prompt to look, not a verdict." />
      <FilterBar show={["course", "section", "faculty"]} />
      <div className="kpis" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))" }}>
        <Kpi label="Students meeting the escalation rule" tone="warn" value={num(overview.data?.kpis.attention_students)} />
        <Kpi label="Students with any flag" value={num(overview.data?.kpis.flagged_students)} />
        <Kpi label="High severity flags" value={num(overview.data?.kpis.severities.high ?? 0)} />
        <Kpi label="Live flags listed" value={num(data?.total)} />
      </div>
      <div className="grid g-main-r section">
        <Card title="Flags by rule" subtitle="Students flagged by each rule">{overview.data ? <RuleBars counts={overview.data.kpis.rules} names={RULES} /> : <LoadingBlock />}</Card>
        <Card title={`Attention heat map · ${overview.data?.heatmap_rows ?? ""}`} subtitle="Students flagged per rule">
          {matrix && matrix.rows.length ? (
            <div style={{ maxHeight: 330, overflow: "auto" }}>
              <div className="heatmap" style={{ gridTemplateColumns: `minmax(90px,150px) repeat(${matrix.rules.length}, minmax(64px,1fr))` }}>
                <div />{matrix.rules.map((r) => <div key={r} className="hm-head" title={RULES[r]?.name}>{RULES[r]?.short}</div>)}
                {matrix.rows.map((row) => (
                  <Row key={row.id} label={row.label} cells={matrix.rules.map((r) => ({ r, v: row.values[r] ?? 0, share: row.cohort ? (row.values[r] ?? 0) / row.cohort : 0 }))} />
                ))}
              </div>
            </div>
          ) : <Empty title="No flags" />}
        </Card>
      </div>
      <div className="filters section">
        <select className="select" aria-label="Rule" value={rule} onChange={(e) => set({ rule: e.target.value || null, offset: null })}><option value="">All rules</option>{Object.entries(RULES).map(([k, v]) => <option key={k} value={k}>{v.name}</option>)}</select>
        <select className="select" aria-label="Severity" value={severity} onChange={(e) => set({ severity: e.target.value || null, offset: null })}><option value="">All severities</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
      </div>
      {error ? <ErrorState error={error} retry={reload} /> : loading || !data ? <LoadingBlock rows={10} /> : (
        <>
          <DataTable rows={data.items} rowKey={(r) => r.id} empty={<Empty title="No live flags match">Every student in this slice clears the rules chosen.</Empty>} columns={[
            { key: "sev", label: "Severity", render: (r) => <SeverityBadge severity={r.severity} /> },
            { key: "student", label: "Student", render: (r) => <Link className="strong" href={`/students/${r.student.id}`}>{r.student.name}<span className="sub">{r.student.register_number}</span></Link> },
            { key: "class", label: "Class", render: (r) => <Link href={`/classes/${r.offering_id}${q}`}>{r.offering}<span className="sub">{r.faculty.join(", ")}</span></Link> },
            { key: "rule", label: "Rule", render: (r) => RULES[r.rule_code]?.name ?? r.rule_code },
            { key: "evidence", label: "Evidence", render: (r) => <span style={{ fontSize: 13.5 }}>{r.message}</span> },
            { key: "since", label: "Updated", render: (r) => date(r.computed_at) },
            { key: "act", label: "", render: (r) => <button className="btn btn-sm" onClick={() => setIntervene(r)}><HeartHandshake size={14} /> Intervene</button> },
          ]} />
          <div className="filters" style={{ marginTop: 14, justifyContent: "flex-end" }}>
            <button className="btn btn-sm" disabled={offset === 0} onClick={() => set({ offset: String(Math.max(0, offset - PAGE)) })}>Previous</button>
            <span className="muted" style={{ fontSize: 14 }}>{data.total ? offset + 1 : 0}–{Math.min(offset + PAGE, data.total)} of {num(data.total)}</span>
            <button className="btn btn-sm" disabled={offset + PAGE >= data.total} onClick={() => set({ offset: String(offset + PAGE) })}>Next</button>
          </div>
        </>
      )}
      {intervene && <InterventionDrawer offeringId={intervene.offering_id} label={intervene.offering} preselect={[intervene.student.id]} onClose={() => setIntervene(null)} onSaved={reload} />}
    </>
  );
}

function Row({ label, cells }: { label: string; cells: { r: string; v: number; share: number }[] }) {
  return (
    <>
      <div className="hm-row">{label}</div>
      {cells.map((c) => <div key={c.r} className="hm-cell" style={{ background: c.v === 0 ? "var(--heat-empty)" : `rgba(194, 53, 42, ${Math.min(0.85, 0.12 + c.share * 2.2)})`, color: c.share > 0.25 ? "#fff" : "#243248" }} title={`${label} · ${RULES[c.r]?.name}: ${c.v}`}>{c.v || ""}</div>)}
    </>
  );
}
