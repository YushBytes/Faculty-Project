"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { useSession, useWorkspace } from "@/lib/auth/session";
import { Badge, Card, PageHead } from "@/components/ui";
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
          <Card title="Session" subtitle="Signed in with a short-lived access token; the refresh token is an httpOnly cookie this page cannot read.">
            <button className="btn btn-danger" onClick={async () => { await logout(); router.replace("/login"); }}><LogOut size={16} /> Sign out</button>
          </Card>
        </div>
      </div>
    </>
  );
}
