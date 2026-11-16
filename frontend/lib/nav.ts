/**
 * The sidebar: which existing pages each role sees, grouped by what people come to do.
 *
 * Grouping only. Who sees what is unchanged from the previous menu (role and the capabilities
 * the backend returns in `/me/workspace`), and every route is enforced again by the API — this
 * is navigation, not access control. `tests/nav.test.ts` pins every role's destinations so a
 * regrouping can never drop a page. Settings is in the sidebar footer (see `SETTINGS`).
 */
import type { ComponentType } from "react";
import {
  Activity, BarChart3, BookOpen, Building2, ClipboardList, FileBarChart, GraduationCap, Layers, LayoutDashboard,
  Network, School, ScrollText, ShieldAlert, Upload, UserCog, Users, UsersRound,
} from "lucide-react";
import type { Role } from "@/lib/api/types";

export type NavItem = { href: string; label: string; icon: ComponentType<{ size?: number }>; hint: string };
export type NavGroup = { label: string; items: NavItem[] };

export const SETTINGS = { href: "/settings", label: "Settings" };

export function navFor(role: Role, caps: Record<string, boolean>): NavGroup[] {
  const academic: NavItem[] = [];
  if (role === "ADMIN") academic.push({ href: "/departments", label: "Departments", icon: Building2, hint: "Every department of the institution" });
  if (role !== "FACULTY") academic.push({ href: "/courses", label: role === "COURSE_COORDINATOR" ? "My courses" : "Courses", icon: BookOpen, hint: "Courses and their sections" });
  if (role !== "FACULTY") academic.push({ href: "/sections", label: "Sections", icon: Layers, hint: "Student groups and their classes" });
  academic.push({ href: "/classes", label: role === "FACULTY" ? "My classes" : "Classes", icon: School, hint: "One course taught to one section: marks, assessments, attention" });
  if (role !== "FACULTY") academic.push({ href: "/faculty", label: "Faculty", icon: UsersRound, hint: "Compare faculty and see who teaches what" });
  if (role === "HOD" || role === "ACADEMIC_HEAD" || role === "ADMIN") academic.push({ href: "/team", label: role === "ACADEMIC_HEAD" ? "Coordinators" : "Team & roles", icon: Network, hint: "Who leads and coordinates what" });

  const admin: NavItem[] = [];
  if (caps.manage_users) admin.push({ href: "/admin/users", label: "People", icon: UserCog, hint: "Accounts, roles and passwords" });
  if (role === "ADMIN") admin.push({ href: "/admin/structure", label: "Academic structure", icon: Users, hint: "Semesters, departments, courses, sections" });
  if (caps.view_audit) admin.push({ href: "/audit", label: "Audit log", icon: ScrollText, hint: "Every change, who made it and when" });

  const groups: NavGroup[] = [
    { label: "Home", items: [{ href: "/dashboard", label: "Overview", icon: LayoutDashboard, hint: "Your workspace at a glance" }] },
    { label: "Academic Management", items: academic },
    {
      label: "Performance Intelligence",
      items: [
        { href: "/analytics", label: "Analytics", icon: BarChart3, hint: "Understand class and student performance" },
        { href: "/assessments", label: "Assessments", icon: ClipboardList, hint: "One assessment across every class" },
      ],
    },
    {
      label: "Student Support",
      items: [
        { href: "/students", label: "Students", icon: GraduationCap, hint: "Find a student and their record" },
        { href: "/attention", label: "Attention", icon: ShieldAlert, hint: "Students who meet the configured attention rules" },
        { href: "/interventions", label: "Interventions", icon: Activity, hint: "Record and follow academic support actions" },
      ],
    },
    { label: "Data & Imports", items: [{ href: "/import", label: "Import TLP marks", icon: Upload, hint: "Upload, check and confirm marks; import history" }] },
    { label: "Reports", items: [{ href: "/reports", label: "Reports", icon: FileBarChart, hint: "Generate and export performance reports" }] },
    { label: "Administration", items: admin },
  ];
  return groups.filter((g) => g.items.length > 0);
}

/** Every destination a role can reach from the sidebar (groups plus the footer). */
export function destinations(role: Role, caps: Record<string, boolean>): string[] {
  return [...navFor(role, caps).flatMap((g) => g.items.map((i) => i.href)), SETTINGS.href];
}
