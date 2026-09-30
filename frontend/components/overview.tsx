"use client";

/**
 * The one dashboard, for every level of the hierarchy. The backend decides the scope (who may
 * see what) and computes every number (`/insights/overview`); this lays it out. `variant`
 * only changes emphasis and order — never what is counted.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import {
  AlertTriangle, BookOpen, CheckCircle2, ClipboardCheck, FileSpreadsheet, GraduationCap, Layers, LineChart as LineIcon,
  ShieldAlert, Sigma, TrendingDown, TrendingUp, Upload, UsersRound,
} from "lucide-react";
import { insightsApi } from "@/lib/api/endpoints";
import type { CompareRow, Overview, ScopeFilters, StudentEntry } from "@/lib/api/types";
import { useApi } from "@/lib/hooks/use-api";
import { useWorkspace } from "@/lib/auth/session";
import { RULES, SEGMENTS, dateTime, num, pct, pctOf } from "@/lib/format";
import { Badge, BarCell, Card, DataTable, Delta, Empty, ErrorState, Kpi, LoadingDashboard, MeasureValue, Tabs } from "@/components/ui";
import { GroupedBars, Heatmap, Histogram, MultiTrend, PassDonut, RankBars, RuleBars, Sparkline, TrendChart } from "@/components/charts";

export type Variant = "institution" | "department" | "portfolio" | "coordinator" | "course" | "faculty" | "section" | "class" | "teacher";

export function periodQuery(filters: ScopeFilters): string {
  const params = new URLSearchParams();
  if (filters.academic_year) params.set("year", filters.academic_year);
  if (filters.semester) params.set("sem", filters.semester);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function useOverview(filters: ScopeFilters) {
  return useApi(() => insightsApi.overview(filters), [filters]);
}

export function OverviewDashboard({ filters, variant, data: given }: { filters: ScopeFilters; variant: Variant; data?: Overview }) {
  const state = useApi(() => insightsApi.overview(filters), [filters], !given);
  const data = given ?? state.data;
  if (!given && state.loading && !data) return <LoadingDashboard />;
  if (!given && state.error) return <ErrorState error={state.error} retry={state.reload} />;
  if (!data) return null;
  return <OverviewBody data={data} variant={variant} filters={filters} />;
}

function OverviewBody({ data, variant, filters }: { data: Overview; variant: Variant; filters: ScopeFilters }) {
  const q = periodQuery(filters);
  const k = data.kpis;
  const noData = k.average.value === null;
  const multiCourse = data.counts.courses > 1;
  const latestMove = [...data.trend].reverse().find((t) => t.change !== null);

  if (data.counts.offerings === 0) {
    return <NoClasses />;
  }

  return (
    <>
      <div className="kpis">
        <Kpi label="Students" icon={<GraduationCap size={15} />} value={num(data.counts.students)} foot={<>{num(k.enrolments)} course enrolments</>} />
        {variant === "class" || variant === "teacher" ? (
          <Kpi label="Classes" icon={<Layers size={15} />} value={data.counts.offerings} foot={<>{data.counts.assessments} published assessments</>} />
        ) : (
          <Kpi label="Sections" icon={<Layers size={15} />} value={data.counts.sections} foot={<>{data.counts.courses} course{data.counts.courses === 1 ? "" : "s"} · {data.counts.offerings} classes</>} />
        )}
        {variant === "class" || variant === "teacher" || variant === "faculty" ? (
          <Kpi label="Median course score" icon={<Sigma size={15} />} value={<MeasureValue m={k.median} />} foot={k.std_dev?.value !== null && k.std_dev ? <>spread ±{k.std_dev.value?.toFixed(1)} pp</> : "course scores"} />
        ) : (
          <Kpi label="Faculty" icon={<UsersRound size={15} />} value={data.counts.faculty} foot={<>{data.counts.coordinators} coordinator{data.counts.coordinators === 1 ? "" : "s"}</>} />
        )}
        <Kpi label="Average course score" tone="accent" icon={<LineIcon size={15} />} value={<MeasureValue m={k.average} />} foot={latestMove ? <><Delta v={latestMove.change} /> at {latestMove.name}</> : <>n = {num(k.scored)}</>} />
        <Kpi label="Pass %" icon={<CheckCircle2 size={15} />} value={<MeasureValue m={k.pass_percent} />} foot={<>{num(k.failed)} below pass mark</>} />
        <Kpi label="Needs attention" tone="warn" icon={<ShieldAlert size={15} />} value={num(k.attention_students)} foot={<>completion {pctOf(k.completion_percent)}</>} />
      </div>

      {noData ? (
        <Card className="section"><Empty title="No marks have been published for this scope yet" icon={<Upload size={24} />}>Upload the TLP reports for these classes from <Link href="/import" style={{ color: "var(--accent)" }}>Import</Link>; the analytics update as soon as they are confirmed.</Empty></Card>
      ) : (
        <>
          <div className="grid g-main section">
            <Card title="Assessment trend" subtitle={multiCourse ? "Mean % per course across its assessments, in teaching order" : "Pooled mean % and pass % per assessment — hover for values, click to open an assessment"}>
              {multiCourse ? <MultiTrend series={data.course_trends} /> : <TrendLink data={data} q={q} />}
            </Card>
            <Card title="Movement between assessments" subtitle={multiCourse ? "Per course, change from the previous assessment" : "Change in mean from the previous assessment"}>
              <Movements data={data} q={q} />
            </Card>
          </div>

          <div className="grid g-3 section">
            <Card title="Distribution of course scores" subtitle={`${num(k.scored)} student course scores, 10-point bins`}><Histogram bins={k.distribution} /></Card>
            <Card title="SRM mark ranges" subtitle="The ranges printed on TLP reports"><Histogram bins={k.srm_ranges} /></Card>
            <Card title="Pass and fail" subtitle="Absent and missing results are never counted as zero"><PassDonut passed={k.passed} failed={k.failed} notScored={k.not_scored} />
              <div className="legend" style={{ justifyContent: "center" }}><span><i style={{ background: "#0d7a69" }} />Pass {num(k.passed)}</span><span><i style={{ background: "#e0786d" }} />Below {num(k.failed)}</span><span><i style={{ background: "#d5dbe4" }} />No score {num(k.not_scored)}</span></div>
            </Card>
          </div>

          <Comparisons data={data} variant={variant} q={q} />

          <div className="grid g-main section">
            <Card title={data.heatmap_rows === "sections" ? "Section × assessment heat map" : "Course × assessment heat map"} subtitle="Mean % — spot the section or paper that moved">
              <Heatmap columns={data.heatmap.columns} rows={data.heatmap.rows} href={(id) => (data.heatmap_rows === "sections" ? `/sections/${id}${q}` : `/courses/${id}${q}`)} />
            </Card>
            <Card title="Attention by rule" subtitle={`${num(k.flagged_students)} students with at least one flag · deterministic rules, not predictions`} actions={<Link className="btn btn-sm" href={`/attention${q}`}>Open</Link>}>
              {Object.keys(k.rules).length ? <RuleBars counts={k.rules} names={RULES} /> : <Empty title="No attention flags" />}
              <div className="legend" style={{ marginTop: 6 }}>{Object.entries(k.severities).map(([s, n]) => <span key={s}><i style={{ background: s === "high" ? "#c2352a" : s === "medium" ? "#b86e00" : "#2459d6" }} />{s} {n}</span>)}</div>
            </Card>
          </div>

          <StudentPanels students={data.students} q={q} segments={k.segments} trends={k.trends} />
        </>
      )}

      <Activity data={data} />
    </>
  );
}

function TrendLink({ data, q }: { data: Overview; q: string }) {
  const router = useRouter();
  const extra = new URLSearchParams(q.replace("?", ""));
  for (const [key, v] of Object.entries(data.filters)) if (v && ["course_id", "section_id", "faculty_id", "offering_id", "department_id"].includes(key)) extra.set(key, String(v));
  return <TrendChart points={data.trend} onSelect={(key) => router.push(`/assessments/${key}?${extra.toString()}`)} />;
}

function Movements({ data, q }: { data: Overview; q: string }) {
  if (data.counts.courses > 1) {
    return (
      <div className="list">
        {data.comparisons.courses.map((c) => {
          const pts = c.trend.filter((t) => t.mean !== null);
          const last = pts[pts.length - 1], prev = pts[pts.length - 2];
          return (
            <div className="list-item" key={c.id}>
              <div className="grow"><Link href={`/courses/${c.id}${q}`}><b>{c.label}</b></Link><small>{c.name}</small></div>
              <Sparkline values={c.trend.map((t) => t.mean)} />
              <div style={{ textAlign: "right", minWidth: 110 }}>
                <b className="tabular">{last ? `${last.name} ${last.mean?.toFixed(1)}%` : "—"}</b>
                <div>{last && prev ? <Delta v={Number(((last.mean ?? 0) - (prev.mean ?? 0)).toFixed(2))} /> : <span className="muted" style={{ fontSize: 12.5 }}>first assessment</span>}</div>
              </div>
            </div>
          );
        })}
      </div>
    );
  }
  return (
    <div className="list">
      {data.trend.map((t) => (
        <div className="list-item" key={t.key}>
          <div className="grow">
            <b>{t.name}</b>
            <small>{t.offerings} class{t.offerings === 1 ? "" : "es"} · pass {pctOf(t.pass_percent)} · completion {pctOf(t.completion_percent)}</small>
          </div>
          <b className="tabular" style={{ fontSize: 17 }}>{pctOf(t.mean)}</b>
          <div style={{ minWidth: 86, textAlign: "right" }}>{t.change === null ? <span className="muted" style={{ fontSize: 12.5 }}>first</span> : <Delta v={t.change} />}</div>
        </div>
      ))}
    </div>
  );
}

type CompareTab = "courses" | "sections" | "faculty" | "semesters" | "departments";

function Comparisons({ data, variant, q }: { data: Overview; variant: Variant; q: string }) {
  const c = data.comparisons;
  const available: { id: CompareTab; label: string; count: number }[] = [];
  const order: CompareTab[] =
    variant === "institution" ? ["departments", "courses", "sections", "faculty", "semesters"]
      : variant === "portfolio" || variant === "department" ? ["courses", "sections", "faculty", "semesters"]
        : variant === "coordinator" || variant === "course" ? ["sections", "faculty", "courses", "semesters"]
          : variant === "faculty" ? ["courses", "sections", "semesters"]
            : ["sections", "courses", "semesters"];
  for (const id of order) {
    const rows = c[id];
    if (!rows || rows.length < 2) continue;
    available.push({ id, label: { courses: "Courses", sections: "Sections", faculty: "Faculty", semesters: "Semesters", departments: "Departments" }[id], count: rows.length });
  }
  const [tab, setTab] = useState<CompareTab | null>(null);
  const current = tab && available.some((a) => a.id === tab) ? tab : available[0]?.id;
  if (!current) return null;
  const rows = c[current];
  const hrefFor = (row: CompareRow) => {
    if (current === "courses") return `/courses/${row.id}${q}`;
    if (current === "sections") return `/sections/${row.id}${q}`;
    if (current === "faculty") return `/faculty/${row.id}${q}`;
    if (current === "departments") return `/departments/${row.id}${q}`;
    return `/analytics${q}`;
  };
  return (
    <section className="section">
      <div className="section-title">
        <div><h2>Comparisons</h2><p>Factual measures of student results — sortable, and every row opens its own view.</p></div>
      </div>
      <Tabs tabs={available.map((a) => ({ id: a.id, label: a.label, count: a.count }))} value={current} onChange={setTab} />
      {current === "semesters" ? (
        <Card><GroupedBars rows={rows} /></Card>
      ) : (
        <div className="grid g-main-r">
          <Card title={`Average by ${current === "faculty" ? "faculty" : current.replace(/s$/, "")}`} subtitle="Click a name to drill down">
            <div style={{ maxHeight: 620, overflowY: "auto" }}><RankBars rows={rows} href={hrefFor} /></div>
          </Card>
          <CompareTable rows={rows} kind={current} href={hrefFor} />
        </div>
      )}
      {current === "faculty" && <p className="muted" style={{ fontSize: 13, marginTop: 10 }}>Faculty figures are the results of the classes each person teaches (a co-taught class counts for each teacher). They describe student results, not teaching quality.</p>}
    </section>
  );
}

function CompareTable({ rows, kind, href }: { rows: CompareRow[]; kind: CompareTab; href: (r: CompareRow) => string }) {
  const router = useRouter();
  return (
    <DataTable
      rows={rows}
      rowKey={(r) => r.id}
      onRowClick={(r) => router.push(href(r))}
      initialSort={{ key: "average", dir: "desc" }}
      maxHeight={640}
      columns={[
        { key: "label", label: kind === "faculty" ? "Faculty" : kind === "courses" ? "Course" : kind === "departments" ? "Department" : "Section", sort: (r) => r.label, render: (r) => <span className="strong">{r.label}{r.name && <span className="sub">{r.name}</span>}{r.course_codes && <span className="sub">{r.course_codes.join(", ")}</span>}{r.coordinators && r.coordinators.length > 0 && <span className="sub">Coordinator: {r.coordinators.join(", ")}</span>}</span> },
        ...(kind !== "sections" ? [{ key: "sections", label: "Sections", align: "right" as const, sort: (r: CompareRow) => r.sections, render: (r: CompareRow) => r.sections }] : [{ key: "courses", label: "Courses", align: "right" as const, sort: (r: CompareRow) => r.courses, render: (r: CompareRow) => r.courses }]),
        { key: "scored", label: "Students", align: "right", sort: (r) => r.scored, render: (r) => num(r.scored) },
        { key: "average", label: "Average", sort: (r) => r.average.value, render: (r) => <BarCell v={r.average.value} /> },
        { key: "pass", label: "Pass %", align: "right", sort: (r) => r.pass_percent.value, render: (r) => pctOf(r.pass_percent) },
        { key: "trend", label: "Trend", render: (r) => <Sparkline values={r.trend.map((t) => t.mean)} /> },
        { key: "change", label: "Latest", align: "right", sort: (r) => r.latest_change, render: (r) => <Delta v={r.latest_change} /> },
        { key: "attention", label: "Attention", align: "right", sort: (r) => r.attention_students, render: (r) => r.attention_students ? <Badge tone="amber">{r.attention_students}</Badge> : <span className="muted">0</span> },
      ]}
    />
  );
}

type ListId = "bottom" | "declining" | "borderline" | "persistently_low" | "improving" | "top";

function StudentPanels({ students, q, segments, trends }: { students: Overview["students"]; q: string; segments: Record<string, number>; trends: Record<string, number> }) {
  const [tab, setTab] = useState<ListId>("bottom");
  const tabs: { id: ListId; label: string }[] = [
    { id: "bottom", label: "Lowest course scores" },
    { id: "declining", label: "Declining" },
    { id: "borderline", label: "Borderline" },
    { id: "persistently_low", label: "Persistently low" },
    { id: "improving", label: "Improving" },
    { id: "top", label: "Highest" },
  ];
  const rows = students[tab];
  const router = useRouter();
  const segmentTotal = useMemo(() => Object.values(segments).reduce((a, b) => a + b, 0), [segments]);
  return (
    <section className="section">
      <div className="section-title"><div><h2>Students</h2><p>Lists come from each student&apos;s own record in each class — trends need at least three assessments.</p></div></div>
      <div className="grid g-main-r">
        <Card title="Where students are" subtitle="Primary segment per student course record">
          <div className="list">
            {Object.entries(SEGMENTS).map(([key, label]) => {
              const n = segments[key] ?? 0;
              return (
                <div className="list-item" key={key}>
                  <div className="grow"><b>{label}</b></div>
                  <div className="meter" style={{ width: 140 }}><i style={{ width: `${segmentTotal ? (n * 100) / segmentTotal : 0}%`, background: key === "persistently_low" || key === "declining" ? "#e0786d" : key === "borderline" ? "#e2b04a" : "#0d7a69" }} /></div>
                  <b className="tabular" style={{ minWidth: 54, textAlign: "right" }}>{num(n)}</b>
                </div>
              );
            })}
          </div>
          <div className="legend" style={{ marginTop: 12 }}>
            <span><TrendingUp size={14} color="#147a3c" />Improving {num(trends.improving ?? 0)}</span>
            <span><TrendingDown size={14} color="#c2352a" />Declining {num(trends.declining ?? 0)}</span>
            <span>Stable {num(trends.stable ?? 0)}</span>
          </div>
        </Card>
        <Card>
          <Tabs tabs={tabs} value={tab} onChange={setTab} />
          <DataTable<StudentEntry>
            rows={rows}
            rowKey={(r) => `${r.id}-${r.offering_id}`}
            onRowClick={(r) => router.push(`/students/${r.id}${q}`)}
            empty={<Empty title="Nobody in this list">No student in scope matches this list.</Empty>}
            columns={[
              { key: "name", label: "Student", render: (r) => <span className="strong">{r.name}<span className="sub">{r.register_number}</span></span> },
              { key: "class", label: "Class", render: (r) => <Link href={`/classes/${r.offering_id}${q}`} onClick={(e) => e.stopPropagation()}>{r.offering}</Link> },
              { key: "score", label: "Course score", align: "right", render: (r) => <b className={r.score !== null && r.score < r.pass_mark ? "cell-bad" : ""}>{pct(r.score)}</b> },
              { key: "latest", label: "Latest", align: "right", render: (r) => pct(r.latest) },
              { key: "flags", label: "Flags", render: (r) => r.flags.length ? <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>{r.flags.slice(0, 2).map((f) => <Badge key={f} tone="amber">{RULES[f]?.short ?? f}</Badge>)}{r.flags.length > 2 && <Badge>+{r.flags.length - 2}</Badge>}</span> : <span className="muted">—</span> },
            ]}
          />
        </Card>
      </div>
    </section>
  );
}

function Activity({ data }: { data: Overview }) {
  const a = data.activity;
  return (
    <section className="section">
      <div className="section-title"><div><h2>Activity</h2><p>Imports, interventions and recorded changes in this scope.</p></div></div>
      <div className="grid g-3">
        <Card title="Recent imports" subtitle={`${num(a.confirmed_imports)} confirmed`} actions={<Link href="/import" className="btn btn-sm"><Upload size={15} /> Import</Link>}>
          {a.imports.length ? (
            <div className="list">{a.imports.map((i) => (
              <div className="list-item" key={i.id}>
                <FileSpreadsheet size={18} color="var(--accent)" />
                <div className="grow"><b style={{ fontSize: 14 }}>{i.file_name}</b><small>{i.offering} · {i.by ?? "—"} · {dateTime(i.at)}</small></div>
                <Badge tone={i.status === "committed" ? "green" : i.status === "discarded" ? undefined : "amber"}>{i.status === "committed" ? `+${i.created ?? 0}` : i.status}</Badge>
              </div>))}
            </div>
          ) : <Empty title="No imports yet" />}
        </Card>
        <Card title="Interventions" subtitle="Recorded support actions" actions={<Link href="/interventions" className="btn btn-sm">Open</Link>}>
          <div className="k-value" style={{ fontFamily: "var(--font-display)", fontSize: 40, fontWeight: 800, color: "var(--ink)" }}>{num(a.interventions)}</div>
          <p className="muted" style={{ marginTop: 6 }}>Outcomes are observed after the next assessment and never attributed to the intervention.</p>
          <div className="list" style={{ marginTop: 10 }}>
            <div className="list-item"><ClipboardCheck size={17} color="var(--accent)" /><div className="grow"><b style={{ fontSize: 14 }}>{num(data.kpis.attention_students)} students meet the escalation rule</b><small>Review them from Attention</small></div></div>
          </div>
        </Card>
        <Card title="Recent changes" subtitle="From the audit log">
          {a.audit.length ? (
            <div className="list">{a.audit.map((row, i) => (
              <div className="list-item" key={i}><AlertTriangle size={16} color="var(--muted-2)" /><div className="grow"><b style={{ fontSize: 14 }}>{row.entity} · {row.action.replaceAll("_", " ")}</b><small>{row.actor ?? "system"} · {dateTime(row.at)}</small></div></div>))}
            </div>
          ) : <Empty title="Nothing recorded">Changes to marks, imports, roles and assignments appear here.</Empty>}
        </Card>
      </div>
    </section>
  );
}

/** Nothing in scope: on a new platform that means nothing has been imported yet. */
function NoClasses() {
  const ws = useWorkspace();
  if (!ws.academic_years.length) {
    return (
      <Card>
        <Empty title="No marks imported yet" icon={<Upload size={24} />}>
          Everything here comes from SRM TLP reports. Import them — Excel, CSV or PDF — and the
          semester, courses, sections, faculty, students and marks are set up from the files.{" "}
          <Link href="/import" style={{ fontWeight: 700 }}>Import TLP marks →</Link>
        </Empty>
      </Card>
    );
  }
  return (
    <Card>
      <Empty title="No classes in this scope for the selected period" icon={<BookOpen size={24} />}>
        Choose another semester or academic year from the period selector, or check the filters.
      </Empty>
    </Card>
  );
}
