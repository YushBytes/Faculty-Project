/**
 * Navigation preservation: the regrouped sidebar offers each role exactly the destinations the
 * previous sidebar did (Settings moved to the footer but is still listed). Quick actions and the
 * tour only point at what the role already has.
 */
import { describe, expect, it } from "vitest";
import { destinations, navFor } from "@/lib/nav";
import { quickActionsFor } from "@/components/quick-actions";
import { tourSteps } from "@/components/tour";
import type { Role, Workspace } from "@/lib/api/types";

/** Capabilities exactly as `/me/workspace` returns them per role (overview/workspace.py). */
function caps(role: Role): Record<string, boolean> {
  return {
    manage_users: ["ADMIN", "HOD", "ACADEMIC_HEAD"].includes(role),
    manage_departments: role === "ADMIN",
    manage_terms: role === "ADMIN",
    manage_sections: ["ADMIN", "HOD"].includes(role),
    manage_courses: ["ADMIN", "HOD", "ACADEMIC_HEAD"].includes(role),
    manage_coordinators: ["ADMIN", "HOD", "ACADEMIC_HEAD"].includes(role),
    assign_faculty: role !== "FACULTY",
    import_marks: true,
    view_audit: ["ADMIN", "HOD", "ACADEMIC_HEAD"].includes(role),
    compare_faculty: role !== "FACULTY",
  };
}

function workspace(role: Role): Workspace {
  return {
    user: { id: `u-${role}`, email: "x@y", full_name: "Test User", role, role_label: role, designation: null, employee_code: null },
    headline: role, institution: "Institution",
    department: role === "ADMIN" ? null : { id: "d-1", code: "CSE", name: "Computer Science" },
    coordinated_courses: [], teaching: [], terms: [], academic_years: [], current_term: null,
    threshold_departments: [],
    capabilities: caps(role) as Workspace["capabilities"],
  };
}

const INSIGHT = ["/analytics", "/assessments", "/students", "/attention", "/interventions"];
/** The previous sidebar's destinations per role (components/shell.tsx before regrouping). */
const BEFORE: Record<Role, string[]> = {
  ADMIN: ["/dashboard", "/departments", "/courses", "/sections", "/faculty", "/team", "/classes", ...INSIGHT, "/import", "/reports", "/admin/users", "/admin/structure", "/audit", "/settings"],
  HOD: ["/dashboard", "/courses", "/sections", "/faculty", "/team", "/classes", ...INSIGHT, "/import", "/reports", "/admin/users", "/audit", "/settings"],
  ACADEMIC_HEAD: ["/dashboard", "/courses", "/sections", "/faculty", "/team", "/classes", ...INSIGHT, "/import", "/reports", "/admin/users", "/audit", "/settings"],
  COURSE_COORDINATOR: ["/dashboard", "/courses", "/sections", "/faculty", "/classes", ...INSIGHT, "/import", "/reports", "/settings"],
  FACULTY: ["/dashboard", "/classes", ...INSIGHT, "/import", "/reports", "/settings"],
};
const ROLES: Role[] = ["ADMIN", "HOD", "ACADEMIC_HEAD", "COURSE_COORDINATOR", "FACULTY"];

describe("sidebar", () => {
  it.each(ROLES)("%s keeps exactly the destinations it had", (role) => {
    expect(destinations(role, caps(role)).sort()).toEqual([...BEFORE[role]].sort());
  });

  it("uses the agreed groups, in order, and hides empty ones", () => {
    expect(navFor("ADMIN", caps("ADMIN")).map((g) => g.label)).toEqual([
      "Home", "Academic Management", "Performance Intelligence", "Student Support", "Data & Imports", "Reports", "Administration",
    ]);
    expect(navFor("FACULTY", caps("FACULTY")).map((g) => g.label)).not.toContain("Administration");
    expect(navFor("COURSE_COORDINATOR", caps("COURSE_COORDINATOR")).map((g) => g.label)).not.toContain("Administration");
  });

  it("follows capabilities, not just the role", () => {
    const hodWithoutPeople = { ...caps("HOD"), manage_users: false, view_audit: false };
    expect(destinations("HOD", hodWithoutPeople)).not.toContain("/admin/users");
    expect(destinations("HOD", hodWithoutPeople)).not.toContain("/audit");
  });

  it("every item has a short explanation", () => {
    for (const role of ROLES) for (const g of navFor(role, caps(role))) for (const i of g.items) expect(i.hint.length).toBeGreaterThan(10);
  });
});

describe("quick actions", () => {
  it.each(ROLES)("%s: every quick action is a page the role already reaches", (role) => {
    const reachable = new Set(destinations(role, caps(role)));
    const actions = quickActionsFor(workspace(role), "?year=2025-26&sem=EVEN");
    expect(actions.length).toBeGreaterThanOrEqual(4);
    for (const a of actions) {
      const path = a.href.split("?")[0];
      // A department's own overview is a detail page under /departments/[id], reached from Home.
      const ok = reachable.has(path) || (role === "HOD" && path === "/departments/d-1");
      expect(ok, `${role}: ${a.href}`).toBe(true);
    }
  });

  it("the Administrator's shortcuts are institution-wide administration", () => {
    expect(quickActionsFor(workspace("ADMIN")).map((a) => a.href.split("?")[0])).toEqual(["/admin/users", "/departments", "/analytics", "/import", "/audit"]);
  });

  it("faculty get their classes and the upload first", () => {
    expect(quickActionsFor(workspace("FACULTY")).slice(0, 2).map((a) => a.label)).toEqual(["My classes", "Upload TLP"]);
  });
});

describe("welcome tour", () => {
  it.each(ROLES)("%s gets four or five steps", (role) => {
    const steps = tourSteps(workspace(role));
    expect(steps.length).toBeGreaterThanOrEqual(4);
    expect(steps.length).toBeLessThanOrEqual(5);
  });

  it("never mentions administration to roles that do not have it", () => {
    const text = (role: Role, ws = workspace(role)) => tourSteps(ws).map((s) => `${s.title} ${s.body}`).join(" ");
    expect(text("FACULTY")).not.toMatch(/People|Audit log|Academic structure/);
    expect(text("COURSE_COORDINATOR")).not.toMatch(/People|Audit log|Academic structure/);
    const hodWithoutPeople = { ...workspace("HOD"), capabilities: { ...caps("HOD"), manage_users: false } as Workspace["capabilities"] };
    expect(text("HOD", hodWithoutPeople)).not.toMatch(/People/);
    expect(text("ADMIN")).toMatch(/exactly one Administrator/);
  });
});
