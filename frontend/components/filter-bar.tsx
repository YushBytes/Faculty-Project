"use client";

/** Working filters, synchronised with the URL so every view is a shareable link. Options come
 * from the unfiltered scope, so a filter never offers something the user cannot see. */
import { X } from "lucide-react";
import { useScope, useUrlState } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { insightsApi } from "@/lib/api/endpoints";

export function FilterBar({ show = ["course", "section", "faculty"] }: { show?: ("course" | "section" | "faculty" | "department")[] }) {
  const scope = useScope();
  const { set } = useUrlState();
  const base = { academic_year: scope.academic_year, semester: scope.semester, course_id: show.includes("course") ? undefined : scope.course_id };
  const options = useApi(() => insightsApi.overview(base), [base]);
  const c = options.data?.comparisons;
  const active = ["department_id", "course_id", "section_id", "faculty_id"].some((k) => scope[k as keyof typeof scope]);
  return (
    <div className="filters" role="group" aria-label="Filters">
      {show.includes("department") && c && c.departments.length > 1 && (
        <select className="select" aria-label="Department" value={scope.department_id ?? ""} onChange={(e) => set({ department_id: e.target.value || null })}>
          <option value="">All departments</option>{c.departments.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
      )}
      {show.includes("course") && (
        <select className="select" aria-label="Course" value={scope.course_id ?? ""} onChange={(e) => set({ course_id: e.target.value || null, section_id: null, faculty_id: null })}>
          <option value="">All courses</option>{c?.courses.map((d) => <option key={d.id} value={d.id}>{d.label} · {d.name}</option>)}
        </select>
      )}
      {show.includes("section") && (
        <select className="select" aria-label="Section" value={scope.section_id ?? ""} onChange={(e) => set({ section_id: e.target.value || null })}>
          <option value="">All sections</option>{c?.sections.map((d) => <option key={d.id} value={d.id}>Section {d.label}</option>)}
        </select>
      )}
      {show.includes("faculty") && c && c.faculty.length > 1 && (
        <select className="select" aria-label="Faculty" value={scope.faculty_id ?? ""} onChange={(e) => set({ faculty_id: e.target.value || null })}>
          <option value="">All faculty</option>{c.faculty.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
      )}
      {active && <button className="btn btn-sm btn-ghost" onClick={() => set({ department_id: null, course_id: null, section_id: null, faculty_id: null })}><X size={15} /> Clear filters</button>}
    </div>
  );
}
