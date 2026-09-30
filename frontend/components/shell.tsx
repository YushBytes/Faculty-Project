"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Activity, BarChart3, BookOpen, Building2, ClipboardList, FileBarChart, GraduationCap, Layers, LayoutDashboard,
  LogOut, Menu, Network, ScrollText, Settings, ShieldAlert, Upload, UserCog, Users, UsersRound, X, School,
} from "lucide-react";
import { useSession } from "@/lib/auth/session";
import type { Role, SemesterPeriod } from "@/lib/api/types";
import { ROLE_LABEL, initials } from "@/lib/format";

type NavItem = { href: string; label: string; icon: React.ComponentType<{ size?: number }> };

function navFor(role: Role, caps: Record<string, boolean>): { label: string; items: NavItem[] }[] {
  const workspace: NavItem[] = [{ href: "/dashboard", label: "Overview", icon: LayoutDashboard }];
  const structure: NavItem[] = [];
  if (role === "ADMIN") structure.push({ href: "/departments", label: "Departments", icon: Building2 });
  if (role !== "FACULTY") structure.push({ href: "/courses", label: role === "COURSE_COORDINATOR" ? "My courses" : "Courses", icon: BookOpen });
  if (role !== "FACULTY") structure.push({ href: "/sections", label: "Sections", icon: Layers });
  if (role !== "FACULTY") structure.push({ href: "/faculty", label: "Faculty", icon: UsersRound });
  if (role === "HOD" || role === "ACADEMIC_HEAD" || role === "ADMIN") structure.push({ href: "/team", label: role === "ACADEMIC_HEAD" ? "Coordinators" : "Team & roles", icon: Network });
  structure.push({ href: "/classes", label: role === "FACULTY" ? "My classes" : "Classes", icon: School });
  const insight: NavItem[] = [
    { href: "/analytics", label: "Analytics", icon: BarChart3 },
    { href: "/assessments", label: "Assessments", icon: ClipboardList },
    { href: "/students", label: "Students", icon: GraduationCap },
    { href: "/attention", label: "Attention", icon: ShieldAlert },
    { href: "/interventions", label: "Interventions", icon: Activity },
  ];
  const act: NavItem[] = [
    { href: "/import", label: "Import TLP marks", icon: Upload },
    { href: "/reports", label: "Reports", icon: FileBarChart },
  ];
  const admin: NavItem[] = [];
  if (caps.manage_users) admin.push({ href: "/admin/users", label: "People", icon: UserCog });
  if (role === "ADMIN") admin.push({ href: "/admin/structure", label: "Academic structure", icon: Users });
  if (caps.view_audit) admin.push({ href: "/audit", label: "Audit log", icon: ScrollText });
  admin.push({ href: "/settings", label: "Settings", icon: Settings });
  return [
    { label: "Workspace", items: [...workspace, ...structure] },
    { label: "Insight", items: insight },
    { label: "Act", items: act },
    { label: "Manage", items: admin },
  ];
}

export function PeriodSelect() {
  const { workspace, period: saved, setPeriod } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  // No semester exists until the first TLP report is imported: nothing to choose yet.
  if (!workspace || !workspace.academic_years.length) return null;
  // A link can pin a period (?year=&sem=); show the one the page is actually using.
  const period = {
    academic_year: params.get("year") ?? saved.academic_year,
    semester: (params.get("sem") as SemesterPeriod | null) ?? saved.semester,
  };
  const update = (next: { academic_year: string | null; semester: SemesterPeriod }) => {
    setPeriod(next);
    const url = new URL(window.location.href);
    if (url.searchParams.has("year") || url.searchParams.has("sem")) {
      url.searchParams.delete("year");
      url.searchParams.delete("sem");
      router.replace(`${pathname}${url.search}`, { scroll: false });
    }
  };
  return (
    <div className="period" aria-label="Academic period">
      <select className="select select-sm" style={{ width: 136 }} aria-label="Academic year" value={period.academic_year ?? ""} onChange={(e) => update({ ...period, academic_year: e.target.value })}>
        {workspace.academic_years.map((y) => <option key={y} value={y}>AY {y}</option>)}
      </select>
      <div className="segmented" role="group" aria-label="Semester">
        {(["ODD", "EVEN", "YEAR"] as SemesterPeriod[]).map((s) => (
          <button key={s} aria-pressed={period.semester === s} onClick={() => update({ ...period, semester: s })}>{s === "YEAR" ? "Full year" : s === "ODD" ? "Odd" : "Even"}</button>
        ))}
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { status, workspace, logout } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (status === "anonymous") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [status, router, pathname]);

  if (status !== "authenticated" || !workspace) {
    return <div className="boot" role="status" aria-label="Loading workspace"><div className="boot-card"><span className="brand-mark" style={{ width: 52, height: 52, margin: "0 auto", borderRadius: 16 }}><GraduationCap size={26} /></span><p className="boot-step">Restoring your session…</p></div></div>;
  }
  const groups = navFor(workspace.user.role, workspace.capabilities);
  const active = (href: string) => pathname === href || pathname.startsWith(`${href}/`);
  return (
    <div className="app-frame">
      {open && <div className="overlay" onClick={() => setOpen(false)} />}
      <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Workspace navigation">
        <Link href="/dashboard" className="brand"><span className="brand-mark"><GraduationCap size={19} /></span>ACADLYTICS</Link>
        <div className="inst-card">
          <b>{workspace.institution}</b>
          <span>{workspace.department?.name ?? "All departments"}</span>
        </div>
        <nav>
          {groups.map((group) => (
            <div className="nav-group" key={group.label}>
              <div className="nav-label">{group.label}</div>
              {group.items.map((item) => (
                <Link key={item.href} href={item.href} onClick={() => setOpen(false)} className={`nav-link ${active(item.href) ? "active" : ""}`} aria-current={active(item.href) ? "page" : undefined}>
                  <item.icon size={18} />
                  <span>{item.label}</span>
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="me">
            <span className="avatar">{initials(workspace.user.full_name)}</span>
            <div style={{ minWidth: 0 }}>
              <b>{workspace.user.full_name}</b>
              <small>{ROLE_LABEL[workspace.user.role]}{workspace.user.employee_code ? ` · ${workspace.user.employee_code}` : ""}</small>
            </div>
          </div>
          <button className="btn btn-sm btn-ghost" style={{ justifyContent: "flex-start" }} onClick={async () => { await logout(); router.replace("/login"); }}><LogOut size={16} /> Sign out</button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="btn btn-ghost btn-icon mobile-toggle" onClick={() => setOpen((o) => !o)} aria-label="Toggle navigation">{open ? <X size={20} /> : <Menu size={20} />}</button>
          <div className="topbar-title"><span className="muted">{workspace.headline}</span></div>
          <div className="topbar-actions">
            <PeriodSelect />
            <span className="role-pill">{ROLE_LABEL[workspace.user.role]}</span>
          </div>
        </header>
        <main className="content" id="main">{children}</main>
      </div>
    </div>
  );
}
