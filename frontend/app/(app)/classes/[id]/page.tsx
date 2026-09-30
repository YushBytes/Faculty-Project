"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Download, Eye, EyeOff, FileBarChart, HeartHandshake, Lightbulb, ListChecks, Upload, UserCog, Wand2 } from "lucide-react";
import { assessmentsApi, insightsApi, offeringsApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/http";
import { useScope, useSession, useWorkspace } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { OverviewDashboard, periodQuery, useOverview } from "@/components/overview";
import { Badge, Card, DataTable, Empty, ErrorState, LoadingBlock, LoadingDashboard, Notice, PageHead, SeverityBadge, Tabs, crumbHref } from "@/components/ui";
import { InterventionDrawer } from "@/components/intervention-drawer";
import { FacultyDrawer } from "@/components/assign";
import { INTERVENTION_KINDS, RULES, date, num } from "@/lib/format";

type Tab = "overview" | "marks" | "assessments" | "attention" | "interventions" | "reports";

export default function ClassPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const ws = useWorkspace();
  const scope = useScope({ offering_id: id, semester: "YEAR" });
  const q = periodQuery(scope);
  const offering = useApi(() => offeringsApi.get(id), [id]);
  const overview = useOverview(scope);
  const [tab, setTab] = useState<Tab>("overview");
  const [intervene, setIntervene] = useState<string[] | null>(null);
  const [assign, setAssign] = useState(false);
  if (offering.error) return <ErrorState error={offering.error} retry={offering.reload} />;
  if (!offering.data || (overview.loading && !overview.data)) return <LoadingDashboard />;
  const o = offering.data;
  const label = `${o.course.code} · ${o.section.name}`;
  const crumbs = [{ href: `/dashboard${q}`, label: overview.data?.scope.root ?? "Workspace" }, ...(overview.data?.scope.crumbs ?? []).filter((c) => c.kind !== "offering").map((c) => ({ href: crumbHref(c, q), label: c.label })), { href: `/courses/${o.course.id}${q}`, label: o.course.code }, { label: `Section ${o.section.name}` }];
  return (
    <>
      <PageHead
        crumbs={crumbs}
        eyebrow={`Class · ${o.term.name}`}
        title={`${o.course.name} — ${o.section.name}`}
        description={<>{o.course.code} · Section {o.section.name} (batch {o.section.batch_year}) · Taught by {o.faculty.map((f) => f.full_name).join(", ") || "—"} · pass mark {o.pass_percent}%</>}
        actions={<>
          {ws.capabilities.assign_faculty && ws.user.role !== "FACULTY" && <button className="btn" onClick={() => setAssign(true)}><UserCog size={17} /> Faculty</button>}
          <button className="btn" onClick={() => setIntervene([])}><HeartHandshake size={17} /> Intervention</button>
          <Link className="btn btn-primary" href={`/import?offering_id=${id}`}><Upload size={17} /> Upload TLP</Link>
        </>}
      />
      <Tabs tabs={[
        { id: "overview", label: "Overview" }, { id: "marks", label: "Marks" }, { id: "assessments", label: "Assessments" },
        { id: "attention", label: "Attention", count: overview.data?.kpis.flagged_students }, { id: "interventions", label: "Interventions" }, { id: "reports", label: "Reports" },
      ]} value={tab} onChange={setTab} />
      {tab === "overview" && (overview.data ? <><EngineInsights id={id} /><div className="section" /><OverviewDashboard filters={scope} variant="class" data={overview.data} /></> : overview.error && <ErrorState error={overview.error} />)}
      {tab === "marks" && <Marks id={id} passMark={o.pass_percent} onIntervene={(ids) => setIntervene(ids)} />}
      {tab === "assessments" && <Assessments id={id} />}
      {tab === "attention" && <ClassAttention id={id} onIntervene={(ids) => setIntervene(ids)} />}
      {tab === "interventions" && <ClassInterventions id={id} scope={scope} />}
      {tab === "reports" && <ClassReports id={id} />}
      {intervene && <InterventionDrawer offeringId={id} label={label} preselect={intervene} onClose={() => setIntervene(null)} onSaved={() => overview.reload()} />}
      {assign && <FacultyDrawer offeringId={id} label={label} departmentId={o.course.department_id} onClose={() => setAssign(false)} onChanged={() => offering.reload()} />}
    </>
  );
}

function EngineInsights({ id }: { id: string }) {
  const { data, loading } = useApi(() => offeringsApi.classAnalytics(id), [id]);
  if (loading || !data || !data.insights.length) return null;
  return (
    <Card title={<span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><Lightbulb size={18} color="var(--amber)" /> What the data says</span>} subtitle="Deterministic statements generated from this class's measured results — no model, no causes">
      {data.insights.slice(0, 6).map((i) => <div className="statement" key={i.code + i.text}><CheckCircle2 size={16} /><span>{i.text}</span></div>)}
    </Card>
  );
}

function Marks({ id, passMark, onIntervene }: { id: string; passMark: number; onIntervene: (ids: string[]) => void }) {
  const router = useRouter();
  const { data, error, loading, reload } = useApi(() => offeringsApi.results(id, false), [id]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const matrix = useMemo(() => {
    const map = new Map<string, Map<string, { status: string; score: number | null; percentage: number | null }>>();
    for (const r of data?.results ?? []) {
      if (!map.has(r.student_id)) map.set(r.student_id, new Map());
      map.get(r.student_id)!.set(r.assessment_id, r);
    }
    return map;
  }, [data]);
  if (error) return <ErrorState error={error} retry={reload} />;
  if (loading || !data) return <LoadingBlock rows={12} />;
  if (!data.students.length) return <Empty title="No students are enrolled in this class" />;
  return (
    <>
      <div className="filters">
        <Badge tone="accent">{data.students.length} students</Badge>
        <Badge>{data.assessments.length} assessments</Badge>
        <span className="muted" style={{ fontSize: 13.5 }}>AB = absent, EX = exempt, — = no mark recorded (never counted as zero). Unpublished assessments are shown faded.</span>
        {picked.size > 0 && <button className="btn btn-sm btn-primary" style={{ marginLeft: "auto" }} onClick={() => onIntervene([...picked])}><HeartHandshake size={15} /> Intervention for {picked.size}</button>}
      </div>
      <div className="table-wrap" style={{ maxHeight: 680, overflow: "auto" }}>
        <table className="table">
          <thead><tr><th style={{ width: 32 }} /><th>Student</th>{data.assessments.map((a) => <th key={a.id} className="r" style={{ opacity: a.is_published ? 1 : 0.5 }}>{a.name}<span className="sub" style={{ fontWeight: 500 }}>/ {a.max_marks}</span></th>)}</tr></thead>
          <tbody>{data.students.map((s) => (
            <tr key={s.id} className="clickable" onClick={() => router.push(`/students/${s.id}`)}>
              <td onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Select ${s.full_name}`} checked={picked.has(s.id)} onChange={() => setPicked((p) => { const n = new Set(p); if (n.has(s.id)) n.delete(s.id); else n.add(s.id); return n; })} /></td>
              <td><span className="strong">{s.full_name}</span><span className="sub">{s.register_number}</span></td>
              {data.assessments.map((a) => {
                const r = matrix.get(s.id)?.get(a.id);
                if (!r) return <td key={a.id} className="r muted" style={{ opacity: a.is_published ? 1 : 0.5 }}>—</td>;
                if (r.status !== "present") return <td key={a.id} className="r" style={{ opacity: a.is_published ? 1 : 0.5 }}><Badge tone={r.status === "absent" ? "amber" : "blue"}>{r.status === "absent" ? "AB" : "EX"}</Badge></td>;
                const low = (r.percentage ?? 100) < passMark;
                return <td key={a.id} className="r" style={{ opacity: a.is_published ? 1 : 0.5 }}><span className={low ? "cell-bad" : ""}>{r.score}</span></td>;
              })}
            </tr>
          ))}</tbody>
        </table>
      </div>
    </>
  );
}

function Assessments({ id }: { id: string }) {
  const { notify } = useSession();
  const { data, error, loading, reload } = useApi(() => offeringsApi.assessments(id), [id]);
  const [busy, setBusy] = useState(false);
  if (error) return <ErrorState error={error} retry={reload} />;
  if (loading || !data) return <LoadingBlock />;
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try { await fn(); notify(ok); reload(); } catch (err) { notify("Not changed", err instanceof ApiError ? err.message : String(err), "error"); } finally { setBusy(false); }
  };
  return (
    <>
      <div className="filters">
        <button className="btn" disabled={busy} onClick={() => run(() => offeringsApi.applyScheme(id), "SRM components created")}><Wand2 size={16} /> Apply SRM scheme</button>
        <button className="btn" onClick={() => offeringsApi.template(id)}><Download size={16} /> Marks template (.xlsx)</button>
        <span className="muted" style={{ fontSize: 13.5 }}>Weightage total {data.weightage_total} · {data.warnings.join(" ")}</span>
      </div>
      <DataTable rows={data.items} rowKey={(a) => a.id} empty={<Empty title="No assessments yet">Apply the SRM scheme for this course type to create its components.</Empty>} columns={[
        { key: "seq", label: "#", render: (a) => a.sequence_no },
        { key: "name", label: "Assessment", render: (a) => <span className="strong">{a.name}<span className="sub">{a.assessment_type}{a.assessment_date ? ` · ${date(a.assessment_date)}` : ""}</span></span> },
        { key: "max", label: "Max", align: "right", render: (a) => a.max_marks },
        { key: "w", label: "Weightage", align: "right", render: (a) => a.weightage },
        { key: "counts", label: "Recorded", render: (a) => <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}><Badge tone="green">{a.result_counts.present} present</Badge>{a.result_counts.absent > 0 && <Badge tone="amber">{a.result_counts.absent} absent</Badge>}{a.result_counts.exempt > 0 && <Badge tone="blue">{a.result_counts.exempt} exempt</Badge>}{a.result_counts.missing > 0 && <Badge>{a.result_counts.missing} missing</Badge>}</span> },
        { key: "pub", label: "Status", render: (a) => a.is_published ? <Badge tone="accent"><Eye size={13} /> Published</Badge> : <Badge><EyeOff size={13} /> Not published</Badge> },
        { key: "act", label: "", render: (a) => <span style={{ display: "flex", gap: 6 }}>
          <button className="btn btn-sm" disabled={busy} onClick={() => run(() => assessmentsApi.update(a.id, { is_published: !a.is_published }), a.is_published ? "Unpublished" : "Published — analytics updated")}>{a.is_published ? "Unpublish" : "Publish"}</button>
          <Link className="btn btn-sm" href={`/import?offering_id=${id}`}><Upload size={14} /> Upload</Link>
        </span> },
      ]} />
      <p className="muted" style={{ fontSize: 13.5, marginTop: 10 }}>Only published assessments count in analytics. A TLP report is matched to its assessment by its test name (FJ-II, FP-I …) and checked against the maximum shown here.</p>
    </>
  );
}

function ClassAttention({ id, onIntervene }: { id: string; onIntervene: (ids: string[]) => void }) {
  const scope = useScope({ offering_id: id, semester: "YEAR" });
  const { data, error, loading, reload } = useApi(() => insightsApi.attention(scope, { limit: 200 }), [id]);
  if (error) return <ErrorState error={error} retry={reload} />;
  if (loading || !data) return <LoadingBlock rows={8} />;
  return (
    <DataTable rows={data.items} rowKey={(r) => r.id} empty={<Empty title="No live attention flags">Every student in this class clears all seven rules at the moment.</Empty>} columns={[
      { key: "sev", label: "Severity", render: (r) => <SeverityBadge severity={r.severity} /> },
      { key: "student", label: "Student", render: (r) => <Link className="strong" href={`/students/${r.student.id}`}>{r.student.name}<span className="sub">{r.student.register_number}</span></Link> },
      { key: "rule", label: "Rule", render: (r) => RULES[r.rule_code]?.name ?? r.rule_code },
      { key: "msg", label: "Evidence", render: (r) => <span style={{ fontSize: 13.5 }}>{r.message}</span> },
      { key: "act", label: "", render: (r) => <button className="btn btn-sm" onClick={() => onIntervene([r.student.id])}><HeartHandshake size={14} /> Intervene</button> },
    ]} />
  );
}

function ClassInterventions({ id, scope }: { id: string; scope: ReturnType<typeof useScope> }) {
  const list = useApi(() => insightsApi.interventions(scope, { limit: 100 }), [id]);
  const outcomes = useApi(() => offeringsApi.interventionOutcomes(id), [id]);
  if (list.error) return <ErrorState error={list.error} retry={list.reload} />;
  if (list.loading || !list.data) return <LoadingBlock rows={6} />;
  const outcomeOf = new Map((outcomes.data?.outcomes ?? []).map((o) => [o.intervention_id, o]));
  return (
    <>
      <Notice>Outcomes compare the targeted students with their classmates before and after the intervention. They are observations: the students were chosen because they were struggling, so a change is never attributed to the intervention.</Notice>
      <div className="section">
        <DataTable rows={list.data.items} rowKey={(r) => r.id} empty={<Empty title="No interventions recorded for this class" />} columns={[
          { key: "date", label: "Date", render: (r) => date(r.recorded_on ?? r.created_at) },
          { key: "kind", label: "Action", render: (r) => <span className="strong">{INTERVENTION_KINDS[r.kind] ?? r.kind}<span className="sub">{r.note}</span></span> },
          { key: "students", label: "Students", render: (r) => r.students.map((s) => s.name).join(", ") },
          { key: "status", label: "Status", render: (r) => <Badge tone={r.status === "completed" ? "green" : r.status === "active" ? "blue" : undefined}>{r.status}</Badge> },
          { key: "outcome", label: "Observed outcome", render: (r) => { const o = outcomeOf.get(r.id); if (!o) return <span className="muted">—</span>; return o.label.value ? <span><Badge tone="violet">{o.label.value.replaceAll("_", " ")}</Badge> <span className="sub">{o.follow_up_assessment ? `at ${o.follow_up_assessment.code}` : ""}</span></span> : <span className="muted" title={o.label.reason ?? ""}>Not yet measurable</span>; } },
          { key: "open", label: "", render: (r) => <Link className="btn btn-sm" href={`/interventions/${r.id}?offering=${id}`}>Open</Link> },
        ]} />
      </div>
    </>
  );
}

function ClassReports({ id }: { id: string }) {
  const { notify } = useSession();
  const [busy, setBusy] = useState<string | null>(null);
  const kinds = [
    ["class_summary", "Class summary", "Health, distribution and assessment statistics"],
    ["assessment_comparison", "Assessment comparison", "What changed between consecutive assessments"],
    ["attention", "Attention", "Every flag with its evidence"],
    ["intervention_outcome", "Intervention outcomes", "Observed outcomes of recorded interventions"],
  ];
  const run = async (kind: string, fmt: string) => {
    setBusy(`${kind}-${fmt}`);
    try { const r = await offeringsApi.classReport(id, kind, fmt); notify("Report downloaded", `${r.fileName} · ${num(Math.round(r.size / 1024))} KB`); }
    catch (err) { notify("Report failed", err instanceof ApiError ? err.message : String(err), "error"); }
    finally { setBusy(null); }
  };
  return (
    <div className="grid g-2">
      {kinds.map(([kind, title, sub]) => (
        <Card key={kind} title={<span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><ListChecks size={18} color="var(--accent)" /> {title}</span>} subtitle={sub}>
          <div style={{ display: "flex", gap: 8 }}>{["pdf", "xlsx", "csv"].map((fmt) => <button key={fmt} className="btn btn-sm" disabled={!!busy} onClick={() => run(kind, fmt)}>{busy === `${kind}-${fmt}` ? "Generating…" : <><FileBarChart size={15} /> {fmt.toUpperCase()}</>}</button>)}</div>
        </Card>
      ))}
      <Card title="Presentation report" subtitle="The charted class report, from the same analytics as this page">
        <Link className="btn btn-primary" href={`/reports?offering_id=${id}&sem=YEAR`}><FileBarChart size={16} /> Open report builder</Link>
      </Card>
    </div>
  );
}

