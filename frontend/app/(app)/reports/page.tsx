"use client";

import { useMemo, useState } from "react";
import { Download, FileBarChart, FileSpreadsheet, FileText, History } from "lucide-react";
import { insightsApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/http";
import type { ScopeFilters, SemesterPeriod } from "@/lib/api/types";
import { useSession, useUrlState, useWorkspace } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { Badge, Card, DataTable, Empty, Kpi, LoadingBlock, MeasureValue, Notice, PageHead } from "@/components/ui";
import { dateTime, num, semesterLabel } from "@/lib/format";

type Level = "scope" | "department" | "course" | "section" | "faculty" | "offering";
const LEVEL_LABEL: Record<Level, string> = { scope: "My whole scope", department: "Department", course: "Course", section: "Section", faculty: "Faculty member", offering: "One class" };

export default function Reports() {
  const ws = useWorkspace();
  const { period, notify } = useSession();
  const { params } = useUrlState();
  const initialLevel: Level = params.get("offering_id") ? "offering" : params.get("faculty_id") ? "faculty" : params.get("section_id") ? "section" : params.get("course_id") ? "course" : params.get("department_id") ? "department" : "scope";
  const [level, setLevel] = useState<Level>(initialLevel);
  const [entity, setEntity] = useState(params.get(`${initialLevel === "scope" ? "x" : initialLevel}_id`) ?? "");
  const [year, setYear] = useState(params.get("year") ?? period.academic_year ?? ws.academic_years[0] ?? "");
  const [semester, setSemester] = useState<SemesterPeriod>((params.get("sem") as SemesterPeriod) ?? period.semester);
  const [kind, setKind] = useState("summary");
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState("");

  const options = useApi(() => insightsApi.overview({ academic_year: year, semester }), [year, semester]);
  const history = useApi(() => insightsApi.reportHistory(), [busy]);
  const offerings = useApi(() => insightsApi.offerings({ academic_year: year, semester }), [year, semester], level === "offering");

  const filters: ScopeFilters = useMemo(() => {
    const base: ScopeFilters = { academic_year: year, semester };
    if (level !== "scope" && entity) (base as Record<string, string>)[`${level}_id`] = entity;
    return base;
  }, [year, semester, level, entity]);
  const preview = useApi(() => insightsApi.overview(filters), [filters], level === "scope" || !!entity);

  const choices = (() => {
    const c = options.data?.comparisons;
    if (!c) return [];
    if (level === "department") return c.departments.map((d) => ({ id: d.id, label: `${d.label} ${d.name ?? ""}` }));
    if (level === "course") return c.courses.map((d) => ({ id: d.id, label: `${d.label} · ${d.name}` }));
    if (level === "section") return c.sections.map((d) => ({ id: d.id, label: `Section ${d.label}` }));
    if (level === "faculty") return c.faculty.map((d) => ({ id: d.id, label: d.label }));
    if (level === "offering") return (offerings.data?.items ?? []).map((o) => ({ id: o.id, label: `${o.course_code} · ${o.section_name}` }));
    return [];
  })();
  const levels: Level[] = ws.user.role === "FACULTY" ? ["scope", "course", "section", "offering"] : ws.user.role === "ADMIN" ? ["scope", "department", "course", "section", "faculty", "offering"] : ["scope", "course", "section", "faculty", "offering"];

  async function generate(format: "pdf" | "xlsx" | "csv", f: ScopeFilters = filters, k = kind) {
    setBusy(format); setFailure("");
    try {
      const r = await insightsApi.report(f, format, k);
      notify("Report downloaded", `${r.fileName} · ${num(Math.max(1, Math.round(r.size / 1024)))} KB`);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      setFailure(message);
      notify("Report was not generated", message, "error");
    } finally { setBusy(null); }
  }

  const p = preview.data;
  return (
    <>
      <PageHead eyebrow="Reports" title="Report builder" description="Presentation-ready PDF with charts, or the same tables as Excel and CSV. Built from exactly the analytics the dashboards show, for any level of your scope and either semester or the full academic year." />
      <div className="grid g-main">
        <Card title="1 · What to report on">
          <div className="grid g-2">
            <label className="field"><span>Scope</span><select className="select" value={level} onChange={(e) => { setLevel(e.target.value as Level); setEntity(""); }}>{levels.map((l) => <option key={l} value={l}>{LEVEL_LABEL[l]}</option>)}</select></label>
            {level !== "scope" && <label className="field"><span>{LEVEL_LABEL[level]}</span><select className="select" value={entity} onChange={(e) => setEntity(e.target.value)}><option value="">Choose…</option>{choices.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}</select></label>}
            <label className="field"><span>Academic year</span><select className="select" value={year} onChange={(e) => setYear(e.target.value)}>{ws.academic_years.map((y) => <option key={y} value={y}>AY {y}</option>)}</select></label>
            <label className="field"><span>Semester</span><select className="select" value={semester} onChange={(e) => setSemester(e.target.value as SemesterPeriod)}><option value="ODD">Odd Semester</option><option value="EVEN">Even Semester</option><option value="YEAR">Full Academic Year</option></select></label>
            <label className="field"><span>Report type</span><select className="select" value={kind} onChange={(e) => setKind(e.target.value)}><option value="summary">Full performance report</option><option value="comparison">Comparison report (courses, sections, faculty)</option><option value="attention">Attention report</option></select></label>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 18, flexWrap: "wrap" }}>
            <button className="btn btn-primary" disabled={!!busy || (level !== "scope" && !entity)} onClick={() => generate("pdf")}><FileText size={17} /> {busy === "pdf" ? "Generating PDF…" : "Download PDF"}</button>
            <button className="btn" disabled={!!busy || (level !== "scope" && !entity)} onClick={() => generate("xlsx")}><FileSpreadsheet size={17} /> {busy === "xlsx" ? "Generating…" : "Excel"}</button>
            <button className="btn" disabled={!!busy || (level !== "scope" && !entity)} onClick={() => generate("csv")}><Download size={17} /> {busy === "csv" ? "Generating…" : "CSV"}</button>
          </div>
          {failure && <div style={{ marginTop: 12 }}><Notice tone="error">{failure}</Notice></div>}
        </Card>
        <Card title="2 · Preview" subtitle={p ? `${p.scope.crumbs.map((c) => c.label).join(" / ") || p.scope.root} · ${semesterLabel(semester)} ${year}` : "Choose a scope"}>
          {level !== "scope" && !entity ? <Empty title="Choose what to report on" /> : preview.loading || !p ? <LoadingBlock rows={5} /> : (
            <>
              <div className="grid g-2">
                <Kpi label="Average" value={<MeasureValue m={p.kpis.average} />} />
                <Kpi label="Pass %" value={<MeasureValue m={p.kpis.pass_percent} />} />
                <Kpi label="Students" value={num(p.counts.students)} foot={`${p.counts.sections} sections · ${p.counts.courses} course${p.counts.courses === 1 ? "" : "s"}`} />
                <Kpi label="Needs attention" value={num(p.kpis.attention_students)} />
              </div>
              <p className="muted" style={{ fontSize: 13.5, marginTop: 12 }}>The report contains these same numbers, the assessment trend, distributions, comparisons, attention lists and conclusions stated from the measured data only.</p>
            </>
          )}
        </Card>
      </div>
      <Card className="section" title={<span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><History size={18} /> Your recent reports</span>} subtitle="Download again regenerates the report from current data for the same scope and period">
        {history.loading && !history.data ? <LoadingBlock rows={4} /> : (
          <DataTable rows={history.data ?? []} rowKey={(r) => r.id} empty={<Empty title="No reports generated yet" icon={<FileBarChart size={24} />} />} columns={[
            { key: "title", label: "Report", render: (r) => <span className="strong">{r.title}<span className="sub">{String(r.scope.period ?? "")}</span></span> },
            { key: "kind", label: "Type", render: (r) => <Badge>{r.kind}</Badge> },
            { key: "fmt", label: "Format", render: (r) => <Badge tone="blue">{r.format.toUpperCase()}</Badge> },
            { key: "size", label: "Size", align: "right", render: (r) => `${num(Math.max(1, Math.round(r.size_bytes / 1024)))} KB` },
            { key: "when", label: "Generated", render: (r) => dateTime(r.created_at) },
            { key: "again", label: "", render: (r) => { const f = Object.fromEntries(Object.entries(r.scope).filter(([k, v]) => v && k !== "period")) as ScopeFilters; return <button className="btn btn-sm" disabled={!!busy} onClick={() => generate(r.format as "pdf", f, r.kind)}><Download size={14} /> Again</button>; } },
          ]} />
        )}
      </Card>
    </>
  );
}
