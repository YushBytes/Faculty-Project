"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, ArrowUpRight, Bell, BookOpen, ChartNoAxesCombined, CircleDot, ClipboardList, FileBarChart, LayoutDashboard, LogOut, Menu, Settings2, ShieldAlert, Sparkles, Upload, Users, X, Building2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/session";
import { SemesterSelector } from "@/components/semester-selector";
import { SkeletonDashboard } from "@/components/skeletons";

const facultyLinks = [
  { label: "Overview", href: "/dashboard", icon: LayoutDashboard, group: "WORKSPACE" },
  { label: "Students", href: "/students", icon: Users },
  { label: "Assessments", href: "/assessments", icon: ClipboardList },
  { label: "Import data", href: "/import", icon: Upload },
  { label: "Analytics", href: "/analytics", icon: ChartNoAxesCombined, group: "INSIGHT" },
  { label: "Attention", href: "/attention", icon: ShieldAlert, badge: "12" },
  { label: "Interventions", href: "/interventions", icon: Activity },
  { label: "Reports", href: "/reports", icon: FileBarChart, group: "MANAGE" },
  { label: "Settings", href: "/settings", icon: Settings2 },
];

const departmentLinks = [
  { label: "Department overview", href: "/dashboard", icon: Building2, group: "DEPARTMENT" },
  ...facultyLinks,
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { user, semester, course, setCourse, logout, ready } = useAuth();
  const [open, setOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const links = user?.role === "hod" ? departmentLinks : facultyLinks;
  useEffect(() => { if (ready && !user) router.replace("/login"); }, [ready, user, router]);
  if (!ready || !user) return <SkeletonDashboard />;
  const activeLabel = links.find((link) => path === link.href || path.startsWith(`${link.href}/`))?.label ?? "Workspace";
  return <div className="app-frame">
    {open && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setOpen(false)} />}
    <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
      <Link href="/dashboard" className="brand app-brand"><span className="brand-mark"><CircleDot size={18} /></span> ACADLYTICS</Link>
      <div className="institution-chip"><span className="institution-seal"><Building2 size={14} /></span><span><b>SRM Institute of Science and Technology</b><small>{user.role === "hod" ? "Department workspace" : "Faculty workspace"}</small></span></div>
      <nav className="side-nav" aria-label="Workspace">
        {links.map((link) => <div key={link.href}>{link.group && <div className="nav-group-label">{link.group}</div>}<Link onClick={() => setOpen(false)} href={link.href} className={`side-link ${path === link.href || path.startsWith(`${link.href}/`) ? "side-link-active" : ""}`}><link.icon size={17} strokeWidth={1.8} /><span>{link.label}</span>{link.badge && <small className="nav-count">{link.badge}</small>}</Link></div>)}
      </nav>
      <div className="sidebar-bottom"><div className="semester-sidebar-label">ACADEMIC PERIOD</div><SemesterSelector /><label className="course-context-label">{user.role === "hod" ? "DEPARTMENT SCOPE" : "CURRENT COURSE"}<select value={course} onChange={(event) => setCourse(event.target.value)} aria-label="Current course context"><option>All assigned courses</option><option>Data Structures · CSE-A</option><option>Database Systems · CSE-B</option><option>Algorithms · CSE-C</option></select></label><div className="profile-row profile-role"><span className="profile-avatar">{user.name.split(" ").map((part) => part[0]).slice(-2).join("")}</span><span><b>{user.name}</b><small>{user.role === "hod" ? "HOD · " : "Faculty · "}{user.department}</small><em className="role-badge">{user.role === "hod" ? "HOD" : "FACULTY"}</em></span></div><button className="logout-button" onClick={() => { logout(); router.replace("/login"); }}><LogOut size={14} /> Sign out</button></div>
    </aside>
    <div className="app-main"><header className="app-topbar"><button className="mobile-menu" aria-label="Open navigation" onClick={() => setOpen(!open)}>{open ? <X size={19} /> : <Menu size={19} />}</button><div className="breadcrumb"><span>{user.role === "hod" ? "Department" : "My workspace"}</span><b>/</b><strong>{activeLabel}</strong><span className="semester-header-pill">{semester}</span></div><div className="topbar-actions"><span className="header-role-badge">{user.role === "hod" ? "HEAD OF DEPARTMENT" : "FACULTY"}</span><span className="demo-status"><i /> DEMO DATA</span><div className="notification-wrap"><button className="icon-action" aria-label="Notifications" aria-expanded={notificationsOpen} onClick={() => setNotificationsOpen(!notificationsOpen)}><Bell size={17} /><i /></button>{notificationsOpen && <div className="notification-popover"><b>Workspace updates</b><p><span /> Assessment records are illustrative demo data.</p><p><span /> Semester context: {semester}</p></div>}</div><span className="topbar-divider" /><button className="help-action">Help <ArrowUpRight size={13} /></button></div></header><main className="app-content">{children}</main><footer className="app-footer"><span>SRM INSTITUTE OF SCIENCE AND TECHNOLOGY <i /> ACADLYTICS</span><span>DEMO WORKSPACE <b>·</b> {semester.toUpperCase()}</span></footer></div>
  </div>;
}

export function PageHeading({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: React.ReactNode }) {
  return <div className="page-heading"><div><div className="page-eyebrow"><span /> {eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="page-heading-actions">{actions}</div>}</div>;
}

export function DemoNotice() { return <div className="demo-notice"><Sparkles size={15} /><span><b>SRM Institute of Science and Technology · Illustrative demo workspace.</b> Names and academic outcomes are fictional and shown to demonstrate the interface.</span><BookOpen size={15} /></div>; }
