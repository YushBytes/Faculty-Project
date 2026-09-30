import type { Measure, Role } from "@/lib/api/types";

export const ROLE_LABEL: Record<Role, string> = {
  ADMIN: "Administrator",
  HOD: "Head of Department",
  ACADEMIC_HEAD: "Academic Head",
  COURSE_COORDINATOR: "Course Coordinator",
  FACULTY: "Faculty",
};
export const ROLE_SHORT: Record<Role, string> = { ADMIN: "Admin", HOD: "HOD", ACADEMIC_HEAD: "Academic Head", COURSE_COORDINATOR: "Coordinator", FACULTY: "Faculty" };

export const RULES: Record<string, { name: string; short: string }> = {
  R1_LOW_PERFORMANCE: { name: "Low performance", short: "Low" },
  R2_FAILED_LATEST: { name: "Below pass mark in latest assessment", short: "Failed latest" },
  R3_REPEATED_LOW: { name: "Repeated low performance", short: "Repeated low" },
  R4_SHARP_DECLINE: { name: "Sharp decline", short: "Sharp decline" },
  R5_DECLINING_TREND: { name: "Declining trend", short: "Declining" },
  R6_LOW_COMPLETION: { name: "Low completion", short: "Low completion" },
  R7_BORDERLINE: { name: "Borderline", short: "Borderline" },
};
export const SEGMENTS: Record<string, string> = {
  high_performer: "High performer",
  improving: "Improving",
  stable: "Stable",
  borderline: "Borderline",
  declining: "Declining",
  persistently_low: "Persistently low",
};
export const INTERVENTION_KINDS: Record<string, string> = {
  academic_support: "Academic support",
  remedial_session: "Remedial session",
  faculty_meeting: "Faculty meeting",
  peer_support: "Peer support",
  additional_practice: "Additional practice",
  counselling_referral: "Counselling referral",
  other: "Other",
};

export const value = (m?: Measure | null) => (m && m.value !== null && m.value !== undefined ? m.value : null);
export const pct = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? "—" : `${v.toFixed(digits)}%`);
export const pctOf = (m?: Measure | null, digits = 1) => pct(value(m), digits);
export const num = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toLocaleString("en-IN"));
export const signed = (v: number | null | undefined, unit = " pp") => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}${unit}`);
export const initials = (name: string) =>
  name.replace(/^(Dr|Mr|Ms|Mrs|Prof)\.?\s+/i, "").split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
export const date = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—");
export const dateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
export const semesterLabel = (s: string | null | undefined) => (s === "ODD" ? "Odd Semester" : s === "EVEN" ? "Even Semester" : "Full Academic Year");

/** A colour for a percentage on the performance scale (used by heat maps and badges). */
export function scaleColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return "var(--heat-empty)";
  if (v < 45) return "var(--heat-1)";
  if (v < 55) return "var(--heat-2)";
  if (v < 62) return "var(--heat-3)";
  if (v < 70) return "var(--heat-4)";
  if (v < 78) return "var(--heat-5)";
  return "var(--heat-6)";
}
