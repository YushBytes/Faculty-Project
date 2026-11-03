"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { orgApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/http";
import { useSession, useWorkspace } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { Badge, Card, DataTable, Drawer, LoadingBlock, Notice, PageHead, Tabs } from "@/components/ui";
import { date, semesterLabel } from "@/lib/format";

type Tab = "departments" | "terms" | "courses" | "sections";

export default function Structure() {
  const ws = useWorkspace();
  const { notify, reloadWorkspace } = useSession();
  const [tab, setTab] = useState<Tab>("terms");
  const [adding, setAdding] = useState<Tab | null>(null);
  const departments = useApi(() => orgApi.departments(), []);
  const terms = useApi(() => orgApi.terms(), []);
  const courses = useApi(() => orgApi.courses(), []);
  const sections = useApi(() => orgApi.sections(), []);
  const makeCurrent = async (id: string) => {
    try { await orgApi.updateTerm(id, { is_current: true }); notify("Current term changed"); terms.reload(); reloadWorkspace(); }
    catch (err) { notify("Not changed", err instanceof ApiError ? err.message : String(err), "error"); }
  };
  return (
    <>
      <PageHead eyebrow="Administration" title="Academic structure" description="Departments, academic years and semesters, courses and sections. The hierarchy lives here — the number of sections is whatever the institution has." actions={<button className="btn btn-primary" onClick={() => setAdding(tab)} disabled={tab === "departments" && ws.user.role !== "ADMIN"}><Plus size={17} /> Add {tab.replace(/s$/, "")}</button>} />
      <Tabs tabs={[{ id: "terms", label: "Terms", count: terms.data?.total }, { id: "departments", label: "Departments", count: departments.data?.total }, { id: "courses", label: "Courses", count: courses.data?.total }, { id: "sections", label: "Sections", count: sections.data?.total }]} value={tab} onChange={setTab} />
      {tab === "terms" && (terms.loading ? <LoadingBlock /> : <DataTable rows={terms.data?.items ?? []} rowKey={(t) => t.id} columns={[
        { key: "code", label: "Code", render: (t) => <span className="strong">{t.code}<span className="sub">{t.name}</span></span> },
        { key: "year", label: "Academic year", render: (t) => t.academic_year },
        { key: "sem", label: "Semester", render: (t) => semesterLabel(t.semester) },
        { key: "dates", label: "Dates", render: (t) => `${date(t.start_date)} – ${date(t.end_date)}` },
        { key: "cur", label: "", render: (t) => t.is_current ? <Badge tone="accent">Current</Badge> : <button className="btn btn-sm" onClick={() => makeCurrent(t.id)}>Make current</button> },
      ]} />)}
      {tab === "departments" && (departments.loading ? <LoadingBlock /> : <DataTable rows={departments.data?.items ?? []} rowKey={(d) => d.id} columns={[{ key: "code", label: "Code", render: (d) => <b>{d.code}</b> }, { key: "name", label: "Name", render: (d) => d.name }]} />)}
      {tab === "courses" && (courses.loading ? <LoadingBlock /> : <DataTable rows={courses.data?.items ?? []} rowKey={(c) => c.id} columns={[
        { key: "code", label: "Code", render: (c) => <b>{c.code}</b> }, { key: "name", label: "Name", render: (c) => c.name },
        { key: "type", label: "Type", render: (c) => <Badge tone="outline">{c.course_type ?? "—"}</Badge> }, { key: "credits", label: "Credits", render: (c) => c.credits ?? "—" },
        { key: "dept", label: "Department", render: (c) => c.department.code }, { key: "coord", label: "Coordinators", render: (c) => c.coordinators.map((x) => x.full_name).join(", ") || "—" },
      ]} />)}
      {tab === "sections" && (sections.loading ? <LoadingBlock /> : <DataTable rows={sections.data?.items ?? []} rowKey={(s) => s.id} maxHeight={640} columns={[
        { key: "name", label: "Section", render: (s) => <b>{s.name}</b> }, { key: "batch", label: "Batch", render: (s) => s.batch_year }, { key: "program", label: "Programme", render: (s) => s.program ?? "—" }, { key: "dept", label: "Department", render: (s) => s.department.code },
      ]} />)}
      {adding && <AddDrawer kind={adding} departments={departments.data?.items ?? []} onClose={() => setAdding(null)} onSaved={() => { setAdding(null); ({ departments, terms, courses, sections })[adding].reload(); reloadWorkspace(); }} />}
      <Card className="section"><p className="muted" style={{ fontSize: 14 }}>Offerings (a course taught to a section in a term) are created with faculty by the HOD, Academic Head or the course&apos;s coordinator; the SRM assessment scheme for the course type can be applied from each class.</p></Card>
    </>
  );
}

function AddDrawer({ kind, departments, onClose, onSaved }: { kind: Tab; departments: { id: string; code: string }[]; onClose: () => void; onSaved: () => void }) {
  const { notify } = useSession();
  const [form, setForm] = useState<Record<string, string>>({ department_id: departments[0]?.id ?? "", semester: "ODD", batch_year: String(new Date().getFullYear()) });
  const [error, setError] = useState("");
  const f = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((x) => ({ ...x, [k]: e.target.value }));
  async function save() {
    setError("");
    try {
      if (kind === "departments") await orgApi.createDepartment({ code: form.code, name: form.name });
      if (kind === "terms") await orgApi.createTerm({ code: form.code, name: form.name, academic_year: form.academic_year, semester: form.semester, start_date: form.start_date, end_date: form.end_date });
      if (kind === "courses") await orgApi.createCourse({ department_id: form.department_id, code: form.code, name: form.name, credits: form.credits ? Number(form.credits) : null });
      if (kind === "sections") await orgApi.createSection({ department_id: form.department_id, name: form.name, batch_year: Number(form.batch_year), program: form.program || null });
      notify("Created", form.code ?? form.name);
      onSaved();
    } catch (err) { setError(err instanceof ApiError ? err.message : String(err)); }
  }
  const dept = <label className="field"><span>Department</span><select className="select" value={form.department_id} onChange={f("department_id")}>{departments.map((d) => <option key={d.id} value={d.id}>{d.code}</option>)}</select></label>;
  return (
    <Drawer title={`Add ${kind.replace(/s$/, "")}`} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={save}>Create</button></>}>
      {kind !== "sections" && <label className="field"><span>Code</span><input className="input" onChange={f("code")} placeholder={kind === "terms" ? "AY2026-27-ODD" : kind === "courses" ? "21CSC301T" : "CSE"} /></label>}
      <label className="field"><span>Name</span><input className="input" onChange={f("name")} placeholder={kind === "sections" ? "A1" : ""} /></label>
      {kind === "terms" && <div className="grid g-2">
        <label className="field"><span>Academic year</span><input className="input" onChange={f("academic_year")} placeholder="2026-27" /></label>
        <label className="field"><span>Semester</span><select className="select" value={form.semester} onChange={f("semester")}><option value="ODD">Odd</option><option value="EVEN">Even</option></select></label>
        <label className="field"><span>Starts</span><input className="input" type="date" onChange={f("start_date")} /></label>
        <label className="field"><span>Ends</span><input className="input" type="date" onChange={f("end_date")} /></label>
      </div>}
      {kind === "courses" && <>{dept}<label className="field"><span>Credits</span><input className="input" type="number" onChange={f("credits")} /></label><p className="muted" style={{ fontSize: 13.5 }}>The SRM course type (T/J/P/L/M) is taken from the last letter of the code.</p></>}
      {kind === "sections" && <>{dept}<div className="grid g-2"><label className="field"><span>Batch (admission year)</span><input className="input" type="number" value={form.batch_year} onChange={f("batch_year")} /></label><label className="field"><span>Programme</span><input className="input" onChange={f("program")} placeholder="B.Tech CSE" /></label></div></>}
      {error && <Notice tone="error">{error}</Notice>}
    </Drawer>
  );
}
