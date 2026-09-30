/** Typed adapters for every backend resource the UI uses. Pages import from here only. */
import { api, download, uploadWithProgress, type Query } from "./http";
import type {
  AssessmentDetail, AttentionItem, AuditRow, CourseRead, Department, ImportPreview, InterventionItem,
  OfferingRead, OfferingRow, Overview, Page, ReportHistory, Role, ScopeFilters, SectionRead,
  StudentRead, Term, TlpUpload, TrendPoint, UserRead, Workspace, CompareRow,
} from "./types";

const q = (filters?: ScopeFilters, extra?: Query): Query => ({ ...(filters as Query), ...(extra ?? {}) });

export const workspaceApi = { get: () => api<Workspace>("/me/workspace") };

export const insightsApi = {
  overview: (filters: ScopeFilters, signal?: AbortSignal) => api<Overview>("/insights/overview", { query: q(filters), signal }),
  offerings: (filters: ScopeFilters) => api<{ period: string; items: OfferingRow[]; total: number }>("/insights/offerings", { query: q(filters) }),
  assessment: (key: string, filters: ScopeFilters) =>
    api<{ period: string; assessment: TrendPoint; previous: TrendPoint | null; sections: { offering_id: string; assessment_id: string; label: string; section_name: string; faculty: string[]; mean: { value: number | null }; median: { value: number | null }; pass_percent: { value: number | null }; completion_percent: { value: number | null }; coverage: Record<string, number>; max_marks: number }[]; faculty: CompareRow[] }>(
      `/insights/assessments/${encodeURIComponent(key)}`, { query: q(filters) }),
  attention: (filters: ScopeFilters, extra: { rule?: string; severity?: string; limit?: number; offset?: number }) =>
    api<{ period: string; total: number; summary: Record<string, number>; severities: Record<string, number>; items: AttentionItem[] }>("/insights/attention", { query: q(filters, extra) }),
  interventions: (filters: ScopeFilters, extra: { limit?: number; offset?: number }) =>
    api<{ period: string; total: number; by_status: Record<string, number>; items: InterventionItem[] }>("/insights/interventions", { query: q(filters, extra) }),
  student: (id: string) => api<StudentOverview>(`/insights/students/${id}`),
  report: (filters: ScopeFilters, format: "pdf" | "xlsx" | "csv", kind: string) => download("/insights/report", q(filters, { format, kind })),
  reportHistory: () => api<ReportHistory[]>("/insights/reports/history"),
};

export type StudentOverview = {
  student: { id: string; register_number: string; full_name: string; email: string | null; batch_year: number; is_active: boolean; section: string | null };
  classes: {
    offering_id: string; course_code: string; course_name: string; section_name: string; term_name: string; semester: string | null;
    academic_year: string; enrollment: string; pass_mark: number;
    analytics: null | {
      profile: {
        history: {
          points: { assessment_id: string; assessment_code: string; sequence_no: number; state: string; percentage: number | null; score: number | null; max_marks: number }[];
          weighted_course_score: { value: number | null; status: string; reason: string | null };
          completion_percent: { value: number | null };
          consistency_std_dev: { value: number | null; status: string };
          trend: { label: { value: string | null; status: string; reason: string | null }; slope: { value: number | null } };
        };
        change_from_previous: { value: number | null; status: string };
      };
      segment: { primary: { value: string | null; status: string } };
      attention: null | { requires_attention: boolean; flags: { rule_code: string; severity: string; message: string; reference_assessments: string[] }[] };
      insights: { code: string; text: string; severity?: string }[];
    };
  }[];
};

export const offeringsApi = {
  get: (id: string) => api<OfferingRead>(`/offerings/${id}`),
  list: (query: Query) => api<Page<OfferingRead>>("/offerings", { query }),
  classAnalytics: (id: string) => api<ClassAnalytics>(`/offerings/${id}/analytics`),
  assessments: (id: string) => api<{ items: AssessmentDetail[]; weightage_total: number; warnings: string[] }>(`/offerings/${id}/assessments`),
  applyScheme: (id: string) => api<{ items: AssessmentDetail[] }>(`/offerings/${id}/assessments/apply-scheme`, { method: "POST" }),
  results: (id: string, publishedOnly = false) => api<OfferingResults>(`/offerings/${id}/results`, { query: { published_only: publishedOnly } }),
  roster: (id: string) => api<Page<{ student: { id: string; register_number: string; full_name: string; is_active: boolean }; status: string }>>(`/offerings/${id}/students`, { query: { limit: 200 } }),
  assignFaculty: (id: string, userId: string) => api<OfferingRead>(`/offerings/${id}/faculty`, { body: { user_id: userId } }),
  unassignFaculty: (id: string, userId: string) => api<OfferingRead>(`/offerings/${id}/faculty/${userId}`, { method: "DELETE" }),
  classReport: (id: string, kind: string, format: string, studentId?: string) => download(`/offerings/${id}/reports/${kind}`, { format, student_id: studentId }),
  template: (id: string) => download(`/offerings/${id}/imports/template`),
  interventionOutcomes: (id: string) => api<{ outcomes: InterventionOutcome[]; insights: { code: string; text: string }[] }>(`/offerings/${id}/interventions/outcomes`),
  createIntervention: (id: string, body: unknown) => api<{ id: string }>(`/offerings/${id}/interventions`, { body }),
  attention: (id: string) => api<{ students: { student: { id: string; register_no: string; name: string }; flags: { rule_code: string; severity: string; message: string }[] }[] }>(`/offerings/${id}/attention`),
};

export type InterventionOutcome = {
  intervention_id: string; follow_up_assessment: { code: string } | null; baseline_assessments: { code: string }[];
  target: OutcomeGroup;
  peers: OutcomeGroup;
  net_change: { value: number | null; status: string; reason: string | null };
  label: { value: string | null; status: string; reason: string | null };
  explanation: { narrative: string; caveats: string[] };
};

export type OfferingResults = {
  assessments: { id: string; name: string; sequence_no: number; max_marks: number; weightage: number; is_published: boolean; assessment_type: string }[];
  students: { id: string; register_number: string; full_name: string; enrollment_status: string; is_active: boolean }[];
  results: { student_id: string; assessment_id: string; status: "present" | "absent" | "exempt"; score: number | null; max_marks_snapshot: number; percentage: number | null }[];
};

export type OutcomeGroup = { name: string; n: number; pre_mean: { value: number | null; status: string }; post_mean: { value: number | null; status: string }; change: { value: number | null; status: string; reason: string | null }; students: { id: string; register_no: string; name: string }[] };

export type ClassAnalytics = {
  offering_id: string;
  health: { cohort_n: number; class_mean: { value: number | null }; pass_percent: { value: number | null }; completion_percent: { value: number | null } };
  change: null | { summary?: string; groups?: unknown[] };
  attention: { total_flags: number; flagged_students: number; students_requiring_attention: number; by_rule: Record<string, number>; by_severity: Record<string, number> };
  insights: { code: string; text: string; severity?: string; category?: string }[];
};

export const assessmentsApi = {
  update: (id: string, body: Partial<{ is_published: boolean; name: string; weightage: number; max_marks: number }>) => api<AssessmentDetail>(`/assessments/${id}`, { method: "PATCH", body }),
  create: (offeringId: string, body: unknown) => api<AssessmentDetail>(`/offerings/${offeringId}/assessments`, { body }),
};

export const importsApi = {
  uploadToOffering: (offeringId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api<ImportPreview>(`/offerings/${offeringId}/imports`, { form });
  },
  preview: (batchId: string, only: "all" | "issues" | "errors" = "issues") => api<ImportPreview>(`/imports/${batchId}/preview`, { query: { only } }),
  fix: (batchId: string, fixes: { row: number; column: string; value: string | null }[]) => api<ImportPreview>(`/imports/${batchId}/fix`, { body: { fixes }, query: { only: "issues" } }),
  exclude: (batchId: string, rows: number[], excluded = true) => api<ImportPreview>(`/imports/${batchId}/exclude`, { body: { rows, excluded }, query: { only: "issues" } }),
  confirm: (batchId: string, publish = true) => api<{ created: number; updated: number; unchanged: number }>(`/imports/${batchId}/confirm`, { method: "POST", query: { publish } }),
  discard: (batchId: string) => api(`/imports/${batchId}/discard`, { method: "POST" }),
  history: (query: Query) => api<Page<ImportPreview["batch"] & { uploaded_by_id: string | null }>>("/imports", { query }),
  tlpUpload: (files: File[], context: { course_id?: string; term_id?: string; offering_id?: string }, onProgress: (f: number) => void = () => undefined) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    Object.entries(context).forEach(([key, value]) => value && form.append(key, value));
    return uploadWithProgress<TlpUpload>("/tlp-uploads", form, onProgress);
  },
  tlpGroup: (groupId: string) => api<TlpUpload>(`/tlp-uploads/${groupId}`),
  tlpConfirm: (groupId: string) => api<TlpUpload>(`/tlp-uploads/${groupId}/confirm`, { method: "POST", query: { publish: true } }),
};

export const orgApi = {
  departments: () => api<Page<Department>>("/departments", { query: { limit: 200 } }),
  createDepartment: (body: { code: string; name: string }) => api<Department>("/departments", { body }),
  terms: () => api<Page<Term>>("/terms", { query: { limit: 200 } }),
  createTerm: (body: unknown) => api<Term>("/terms", { body }),
  updateTerm: (id: string, body: unknown) => api<Term>(`/terms/${id}`, { method: "PATCH", body }),
  courses: (query: Query = {}) => api<Page<CourseRead>>("/courses", { query: { limit: 200, ...query } }),
  course: (id: string) => api<CourseRead>(`/courses/${id}`),
  createCourse: (body: unknown) => api<CourseRead>("/courses", { body }),
  addCoordinator: (courseId: string, userId: string) => api<CourseRead>(`/courses/${courseId}/coordinators`, { body: { user_id: userId } }),
  removeCoordinator: (courseId: string, userId: string) => api<CourseRead>(`/courses/${courseId}/coordinators/${userId}`, { method: "DELETE" }),
  sections: (query: Query = {}) => api<Page<SectionRead>>("/sections", { query: { limit: 200, ...query } }),
  section: (id: string) => api<SectionRead>(`/sections/${id}`),
  createSection: (body: unknown) => api<SectionRead>("/sections", { body }),
};

export const usersApi = {
  list: (query: Query) => api<Page<UserRead>>("/users", { query }),
  get: (id: string) => api<UserRead>(`/users/${id}`),
  create: (body: { email: string; full_name: string; password: string; role: Role; department_id?: string | null; employee_code?: string | null; designation?: string | null }) => api<UserRead>("/users", { body }),
  update: (id: string, body: Partial<{ full_name: string; role: Role; department_id: string | null; password: string; employee_code: string | null; designation: string | null }>) => api<UserRead>(`/users/${id}`, { method: "PATCH", body }),
  activate: (id: string) => api<UserRead>(`/users/${id}/activate`, { method: "POST" }),
  deactivate: (id: string) => api<UserRead>(`/users/${id}/deactivate`, { method: "POST" }),
};

export const studentsApi = {
  list: (query: Query) => api<Page<StudentRead>>("/students", { query }),
  get: (id: string) => api<StudentRead>(`/students/${id}`),
};

export const auditApi = { list: (query: Query) => api<Page<AuditRow>>("/audit-logs", { query }) };
