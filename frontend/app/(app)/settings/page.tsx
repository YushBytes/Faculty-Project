"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Compass, KeyRound, LogOut, SlidersHorizontal } from "lucide-react";
import { replayTour } from "@/components/tour";
import { accountApi, orgApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/http";
import { useSession, useWorkspace } from "@/lib/auth/session";
import { Badge, Card, DataTable, Empty, ErrorState, LoadingBlock, PageHead } from "@/components/ui";
import { useApi } from "@/lib/hooks/use-api";
import { PeriodSelect } from "@/components/shell";
import { ROLE_LABEL } from "@/lib/format";

export default function Settings() {
  const ws = useWorkspace();
  const { logout } = useSession();
  const router = useRouter();
  const caps = Object.entries(ws.capabilities).filter(([, v]) => v).map(([k]) => k.replaceAll("_", " "));
  return (
    <>
      <PageHead eyebrow="Settings" title="Your account" description="Your role and scope come from the institution's records. Ask your HOD or the Administrator to change them." />
      <div className="grid g-2">
        <Card title="Profile">
          <div className="list">
            <div className="list-item"><div className="grow"><b>Name</b></div>{ws.user.full_name}</div>
            <div className="list-item"><div className="grow"><b>Email</b></div>{ws.user.email}</div>
            <div className="list-item"><div className="grow"><b>Role</b></div><Badge tone="accent">{ROLE_LABEL[ws.user.role]}</Badge></div>
            <div className="list-item"><div className="grow"><b>Designation</b></div>{ws.user.designation ?? "—"}</div>
            <div className="list-item"><div className="grow"><b>Staff id</b></div>{ws.user.employee_code ?? "—"}</div>
            <div className="list-item"><div className="grow"><b>Department</b></div>{ws.department?.name ?? "All"}</div>
            {ws.coordinated_courses.length > 0 && <div className="list-item"><div className="grow"><b>Coordinates</b></div>{ws.coordinated_courses.map((c) => c.code).join(", ")}</div>}
            <div className="list-item"><div className="grow"><b>Classes taught</b></div>{ws.teaching.length}</div>
          </div>
        </Card>
        <div className="grid">
          <Card title="Default academic period" subtitle="Remembered on this device"><PeriodSelect /></Card>
          <Card title="What you can do" subtitle="Enforced by the server on every request"><div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>{caps.map((c) => <Badge key={c}>{c}</Badge>)}</div></Card>
          <Thresholds />
          <Card title="Welcome tour" subtitle="A short walk through the parts of ACADLYTICS your role uses.">
            <button className="btn" onClick={replayTour}><Compass size={16} /> Replay tour</button>
          </Card>
          <ChangePassword />
          <Card title="Session" subtitle="Signed in with a short-lived access token; the refresh token is an httpOnly cookie this page cannot read.">
            <button className="btn btn-danger" onClick={async () => { await logout(); router.replace("/login"); }}><LogOut size={16} /> Sign out</button>
          </Card>
        </div>
      </div>
    </>
  );
}

function ChangePassword() {
  const { logout } = useSession();
  const router = useRouter();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const up = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const mismatch = form.confirm !== "" && form.next !== form.confirm;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    if (form.next.length < 8) return setError("The new password needs at least 8 characters.");
    if (form.next !== form.confirm) return setError("The two new passwords do not match.");
    setBusy(true);
    try {
      await accountApi.changePassword(form.current, form.next);
      // Every session was revoked by the server; sign in again with the new password.
      await logout();
      router.replace("/login?changed=1");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The password could not be changed.");
      setBusy(false);
    }
  }

  return (
    <Card title="Change password" subtitle="You will be signed out everywhere and sign in again with the new password.">
      <form className="login-form" onSubmit={submit}>
        <label className="field"><span>Current password</span><input className="input" type="password" autoComplete="current-password" required value={form.current} onChange={up("current")} /></label>
        <label className="field"><span>New password</span><input className="input" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={form.next} onChange={up("next")} placeholder="At least 8 characters" /></label>
        <label className="field"><span>Repeat new password</span><input className="input" type="password" autoComplete="new-password" required value={form.confirm} onChange={up("confirm")} aria-invalid={mismatch} /></label>
        {(error || mismatch) && <div className="notice notice-error" role="alert">{error || "The two new passwords do not match."}</div>}
        <button className="btn btn-primary" disabled={busy}><KeyRound size={16} /> {busy ? "Changing…" : "Change password"}</button>
      </form>
    </Card>
  );
}

/** Display names for the threshold keys analytics knows (app/modules/analytics/core/thresholds.py). */
const THRESHOLD_LABEL: Record<string, string> = {
  low_performance_percent: "Low performance (R1), %",
  high_performance_percent: "High performer, %",
  repeated_low_count: "Repeated low (R3), assessments",
  decline_drop_pp: "Sharp decline (R4), pp",
  trend_delta_pp: "Trend (R5), pp per assessment",
  low_completion_percent: "Low completion (R6), %",
  borderline_band_pp: "Borderline band (R7), pp",
  cohort_shift_pp: "Cohort shift, pp",
  improvement_delta_pp: "Improvement, pp",
  min_group_n: "Minimum group size",
  min_trend_points: "Minimum assessments for a trend",
  min_consistency_points: "Minimum assessments for consistency",
  min_outcome_group_n: "Minimum outcome group size",
};

/**
 * The analytics thresholds of the departments this user may read. Which departments appear is
 * the server's decision (`workspace.threshold_departments`); the API refuses (404) any other
 * department even if asked directly, so this card is a view, not the access control.
 */
function Thresholds() {
  const ws = useWorkspace();
  const departments = ws.threshold_departments;
  const [chosen, setChosen] = useState(ws.department?.id && departments.some((d) => d.id === ws.department?.id) ? ws.department.id : departments[0]?.id ?? "");
  const settings = useApi(() => orgApi.departmentSettings(chosen), [chosen], !!chosen);
  if (!departments.length) return null;
  const current = departments.find((d) => d.id === chosen);
  return (
    <Card title={<span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><SlidersHorizontal size={18} /> Analytics thresholds</span>}
      subtitle={current?.can_edit ? "Overrides set for the department. You can change them (administrator or HOD)." : "Overrides set for the department. Read-only for your role."}>
      {departments.length > 1 && (
        <label className="field" style={{ marginBottom: 12 }}><span>Department</span>
          <select className="select" aria-label="Department for thresholds" value={chosen} onChange={(e) => setChosen(e.target.value)}>
            {departments.map((d) => <option key={d.id} value={d.id}>{d.code} · {d.name}</option>)}
          </select>
        </label>
      )}
      {settings.error ? <ErrorState error={settings.error} retry={settings.reload} /> : settings.loading || !settings.data ? <LoadingBlock rows={3} /> : (
        <>
          <DataTable rows={settings.data} rowKey={(r) => r.key} empty={<Empty title="No overrides">Every threshold uses the system default for this department.</Empty>} columns={[
            { key: "key", label: "Threshold", render: (r) => <span className="strong">{THRESHOLD_LABEL[r.key] ?? r.key}<span className="sub">{r.key}</span></span> },
            { key: "value", label: "Value", align: "right", render: (r) => typeof r.value === "object" ? JSON.stringify(r.value) : String(r.value) },
          ]} />
          <p className="muted" style={{ fontSize: 13.5, marginTop: 8 }}>Thresholds not listed use the system default. A class can override them; each class&apos;s analytics show the value in force and where it came from.</p>
        </>
      )}
    </Card>
  );
}
