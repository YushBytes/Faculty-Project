"use client";

/**
 * Role-specific shortcuts above the existing dashboard. Every link is an existing page the role
 * already reaches from the sidebar (same role and capability rules as `lib/nav.ts`); nothing here
 * grants access — the pages and the API enforce scope as before.
 */
import Link from "next/link";
import type { ComponentType } from "react";
import {
  Activity, BarChart3, BookOpen, Building2, FileBarChart, Layers, Network, School, ScrollText, ShieldAlert, Upload, UserCog, UsersRound,
} from "lucide-react";
import type { Workspace } from "@/lib/api/types";

export type QuickAction = { href: string; label: string; hint: string; icon: ComponentType<{ size?: number }> };

export function quickActionsFor(ws: Workspace, query = ""): QuickAction[] {
  const caps = ws.capabilities;
  const reports: QuickAction = { href: `/reports${query}`, label: "Reports", hint: "PDF, Excel, CSV", icon: FileBarChart };
  const analytics = (label: string): QuickAction => ({ href: `/analytics${query}`, label, hint: "Class performance", icon: BarChart3 });
  const attention: QuickAction = { href: `/attention${query}`, label: "Review attention", hint: "Flagged students", icon: ShieldAlert };
  const faculty: QuickAction = { href: `/faculty${query}`, label: "Faculty", hint: "Who teaches what", icon: UsersRound };
  switch (ws.user.role) {
    case "FACULTY":
      return [
        { href: `/classes${query}`, label: "My classes", hint: "Marks and attention", icon: School },
        { href: "/import", label: "Upload TLP", hint: "Check, then confirm", icon: Upload },
        analytics("Analytics"),
        attention,
        reports,
      ];
    case "COURSE_COORDINATOR":
      return [
        { href: `/courses${query}`, label: "My courses", hint: "All their sections", icon: BookOpen },
        { href: `/sections${query}`, label: "Sections", hint: "Compare sections", icon: Layers },
        faculty,
        analytics("Course analytics"),
        reports,
      ];
    case "ACADEMIC_HEAD":
      return [
        { href: `/courses${query}`, label: "Course portfolio", hint: "Every course", icon: BookOpen },
        { href: "/team", label: "Coordinators", hint: "Who leads each course", icon: Network },
        faculty,
        analytics("Analytics"),
        reports,
      ];
    case "HOD":
      return [
        ...(ws.department ? [{ href: `/departments/${ws.department.id}${query}`, label: "Department overview", hint: ws.department.name, icon: Building2 }] : []),
        analytics("Department analytics"),
        attention,
        { href: `/interventions${query}`, label: "Interventions", hint: "Support recorded", icon: Activity },
        faculty,
        reports,
      ];
    default:
      return [
        ...(caps.manage_users ? [{ href: "/admin/users", label: "Manage users", hint: "Accounts and roles", icon: UserCog }] : []),
        ...(caps.manage_departments ? [{ href: "/departments", label: "Departments", hint: "Every department", icon: Building2 }] : []),
        analytics("Institution analytics"),
        { href: "/import", label: "Imports", hint: "Upload and history", icon: Upload },
        ...(caps.view_audit ? [{ href: "/audit", label: "Audit log", hint: "Every change", icon: ScrollText }] : []),
      ];
  }
}

export function QuickActions({ workspace, query }: { workspace: Workspace; query?: string }) {
  const actions = quickActionsFor(workspace, query);
  return (
    <nav className="quick-actions" aria-label="Quick actions">
      {actions.map((a) => (
        <Link key={a.label} href={a.href} className="quick-action">
          <span className="qa-icon" aria-hidden="true"><a.icon size={17} /></span>
          <span className="qa-text"><b>{a.label}</b><small>{a.hint}</small></span>
        </Link>
      ))}
    </nav>
  );
}
