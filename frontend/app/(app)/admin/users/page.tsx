"use client";

import { useState } from "react";
import { KeyRound, Plus, Search } from "lucide-react";
import { orgApi, usersApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/http";
import type { Role, UserRead } from "@/lib/api/types";
import { useSession, useUrlState, useWorkspace } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { Badge, DataTable, Drawer, ErrorState, LoadingBlock, Notice, PageHead } from "@/components/ui";
import { ROLE_LABEL, dateTime, num } from "@/lib/format";

const ALL_ROLES: Role[] = ["ADMIN", "HOD", "ACADEMIC_HEAD", "COURSE_COORDINATOR", "FACULTY"];

export default function People() {
  const ws = useWorkspace();
  const { params, set } = useUrlState();
  const role = (params.get("role") as Role | null) ?? "";
  const q = params.get("q") ?? "";
  const [text, setText] = useState(q);
  const [edit, setEdit] = useState<UserRead | "new" | null>(null);
  const offset = Number(params.get("offset") ?? 0);
  const { data, error, loading, reload } = useApi(() => usersApi.list({ role: role || undefined, q: q || undefined, limit: 50, offset, department_id: ws.user.role === "ADMIN" ? undefined : ws.department?.id }), [role, q, offset]);
  const manageable: Role[] = ws.user.role === "ADMIN" ? ALL_ROLES : ws.user.role === "HOD" ? ["ACADEMIC_HEAD", "COURSE_COORDINATOR", "FACULTY"] : ["COURSE_COORDINATOR", "FACULTY"];
  return (
    <>
      <PageHead eyebrow="People" title="People & roles" description={ws.user.role === "ADMIN" ? "Every account in the institution. There is exactly one Administrator, and one HOD and one Academic Head per department." : `Staff of ${ws.department?.name}. You can manage: ${manageable.map((r) => ROLE_LABEL[r]).join(", ")}.`} actions={<button className="btn btn-primary" onClick={() => setEdit("new")}><Plus size={17} /> Add person</button>} />
      <form className="filters" onSubmit={(e) => { e.preventDefault(); set({ q: text || null, offset: null }); }}>
        <div className="search"><Search size={16} /><input className="input" placeholder="Name, email or staff id" value={text} onChange={(e) => setText(e.target.value)} /></div>
        <select className="select" value={role} onChange={(e) => set({ role: e.target.value || null, offset: null })}><option value="">All roles</option>{ALL_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select>
        <button className="btn">Search</button>
        {data && <span className="muted">{num(data.total)} people</span>}
      </form>
      {error ? <ErrorState error={error} retry={reload} /> : loading || !data ? <LoadingBlock rows={12} /> : (
        <>
          <DataTable rows={data.items} rowKey={(u) => u.id} onRowClick={(u) => setEdit(u)} columns={[
            { key: "name", label: "Name", render: (u) => <span className="strong">{u.full_name}<span className="sub">{u.email}</span></span> },
            { key: "role", label: "Role", render: (u) => <Badge tone={u.role === "ADMIN" ? "violet" : u.role === "HOD" || u.role === "ACADEMIC_HEAD" ? "blue" : u.role === "COURSE_COORDINATOR" ? "accent" : undefined}>{ROLE_LABEL[u.role]}</Badge> },
            { key: "code", label: "Staff id", render: (u) => u.employee_code ?? "—" },
            { key: "title", label: "Designation", render: (u) => u.designation ?? "—" },
            { key: "login", label: "Last sign-in", render: (u) => dateTime(u.last_login_at) },
            { key: "status", label: "Status", render: (u) => u.is_active ? <Badge tone="green">Active</Badge> : <Badge>Deactivated</Badge> },
          ]} />
          <div className="filters" style={{ marginTop: 14, justifyContent: "flex-end" }}>
            <button className="btn btn-sm" disabled={offset === 0} onClick={() => set({ offset: String(Math.max(0, offset - 50)) })}>Previous</button>
            <button className="btn btn-sm" disabled={offset + 50 >= data.total} onClick={() => set({ offset: String(offset + 50) })}>Next</button>
          </div>
        </>
      )}
      {edit && <UserDrawer user={edit === "new" ? null : edit} roles={manageable} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); }} />}
    </>
  );
}

function UserDrawer({ user, roles, onClose, onSaved }: { user: UserRead | null; roles: Role[]; onClose: () => void; onSaved: () => void }) {
  const ws = useWorkspace();
  const { notify } = useSession();
  const departments = useApi(() => orgApi.departments(), []);
  const [form, setForm] = useState({ full_name: user?.full_name ?? "", email: user?.email ?? "", role: (user?.role ?? roles[roles.length - 1]) as Role, department_id: user?.department_id ?? ws.department?.id ?? "", employee_code: user?.employee_code ?? "", designation: user?.designation ?? "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const up = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const canEdit = !user || roles.includes(user.role);
  async function save() {
    setBusy(true); setError("");
    try {
      if (!user) await usersApi.create({ ...form, department_id: form.department_id || null, employee_code: form.employee_code || null, designation: form.designation || null });
      else await usersApi.update(user.id, { full_name: form.full_name, role: form.role, ...(ws.user.role === "ADMIN" ? { department_id: form.department_id || null } : {}), employee_code: form.employee_code || null, designation: form.designation || null, ...(form.password ? { password: form.password } : {}) });
      notify(user ? "Saved" : "Account created", `${form.full_name} · ${ROLE_LABEL[form.role]}`);
      onSaved();
    } catch (err) { setError(err instanceof ApiError ? err.message : String(err)); } finally { setBusy(false); }
  }
  async function toggle() {
    if (!user) return;
    setBusy(true); setError("");
    try { await (user.is_active ? usersApi.deactivate(user.id) : usersApi.activate(user.id)); notify(user.is_active ? "Deactivated" : "Reactivated", user.full_name); onSaved(); }
    catch (err) { setError(err instanceof ApiError ? err.message : String(err)); } finally { setBusy(false); }
  }
  return (
    <Drawer title={user ? user.full_name : "Add a person"} subtitle={user?.email} onClose={onClose} footer={<>{user && canEdit && <button className="btn btn-danger" disabled={busy} onClick={toggle}>{user.is_active ? "Deactivate" : "Reactivate"}</button>}<button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy || !canEdit} onClick={save}>{user ? "Save changes" : "Create account"}</button></>}>
      {!canEdit && <Notice tone="warn">This account is above your level; you can view it but not change it.</Notice>}
      <label className="field"><span>Full name</span><input className="input" value={form.full_name} onChange={up("full_name")} /></label>
      {!user && <label className="field"><span>Email</span><input className="input" type="email" value={form.email} onChange={up("email")} /></label>}
      <div className="grid g-2">
        <label className="field"><span>Role</span><select className="select" value={form.role} onChange={up("role")}>{(user && !roles.includes(user.role) ? [user.role] : roles).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select></label>
        <label className="field"><span>Department</span><select className="select" value={form.department_id} onChange={up("department_id")} disabled={ws.user.role !== "ADMIN"}><option value="">None</option>{departments.data?.items.map((d) => <option key={d.id} value={d.id}>{d.code}</option>)}</select></label>
        <label className="field"><span>Staff id</span><input className="input" value={form.employee_code} onChange={up("employee_code")} placeholder="e.g. 103059" /></label>
        <label className="field"><span>Designation</span><input className="input" value={form.designation} onChange={up("designation")} placeholder="Assistant Professor" /></label>
      </div>
      <label className="field"><span><KeyRound size={13} /> {user ? "Reset password (optional)" : "Initial password"}</span><input className="input" type="password" value={form.password} onChange={up("password")} placeholder="At least 8 characters" /></label>
      {user && <p className="muted" style={{ fontSize: 13.5 }}>Role, department and password changes are recorded in the audit log; a password reset signs the person out everywhere.</p>}
      {error && <Notice tone="error">{error}</Notice>}
    </Drawer>
  );
}
