/** Wire types, as the backend sends them (see /docs on the API). */

export type Role = "ADMIN" | "HOD" | "ACADEMIC_HEAD" | "COURSE_COORDINATOR" | "FACULTY";
export type SemesterPeriod = "ODD" | "EVEN" | "YEAR";
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type Measure = { value: number | null; status: "ok" | "insufficient_data"; n: number; reason: string | null };

export type Workspace = {
  user: { id: string; email: string; full_name: string; role: Role; role_label: string; designation: string | null; employee_code: string | null };
  headline: string;
  institution: string;
  department: { id: string; code: string; name: string } | null;
  coordinated_courses: { id: string; code: string; name: string; course_type: string | null }[];
  teaching: {
    offering_id: string; course_id: string; course_code: string; course_name: string;
    section_id: string; section_name: string; term_id: string; term_code: string; academic_year: string; semester: string | null;
  }[];
  terms: { id: string; code: string; name: string; academic_year: string; semester: "ODD" | "EVEN" | null; is_current: boolean }[];
  academic_years: string[];
  current_term: { id: string; academic_year: string; semester: "ODD" | "EVEN" | null; name: string } | null;
  capabilities: Record<
    | "manage_users" | "manage_departments" | "manage_terms" | "manage_sections" | "manage_courses"
    | "manage_coordinators" | "assign_faculty" | "import_marks" | "view_audit" | "compare_faculty",
    boolean
  >;
};

export type ScopeFilters = {
  academic_year?: string | null;
  semester?: SemesterPeriod | null;
  term_id?: string | null;
  department_id?: string | null;
  course_id?: string | null;
  section_id?: string | null;
  faculty_id?: string | null;
  coordinator_id?: string | null;
  offering_id?: string | null;
};

export type TrendPoint = {
  key: string; name: string; sequence?: number; offerings?: number; max_marks?: number[];
  mean: Measure; median?: Measure; std_dev?: Measure; pass_percent?: Measure; completion_percent?: Measure | null;
  coverage?: Record<string, number>; distribution?: { range: string; count: number }[]; change: number | null;
};

export type CompareRow = {
  id: string; label: string; offerings: number; enrolments: number; scored: number;
  average: Measure; median: Measure; pass_percent: Measure; fail_percent: Measure; completion_percent: Measure;
  attention_students: number; trend: { key: string; name: string; mean: number | null }[]; latest_change: number | null;
  sections: number; courses: number;
  name?: string; course_type?: string | null; coordinators?: string[]; faculty?: number; batch_year?: number; course_codes?: string[];
};

export type StudentEntry = {
  id: string; register_number: string; name: string; score: number | null; segment: string | null; trend: string | null;
  latest: number | null; flags: string[]; offering_id: string; offering: string; pass_mark: number;
};

export type Kpis = {
  offerings: number; enrolments: number; scored: number; passed: number; failed: number; not_scored: number;
  average: Measure; median: Measure; std_dev: Measure | null; pass_percent: Measure; fail_percent: Measure; completion_percent: Measure;
  coverage: Record<string, number>; attention_students: number; flagged_students: number;
  rules: Record<string, number>; severities: Record<string, number>; segments: Record<string, number>; trends: Record<string, number>;
  distribution: { range: string; count: number; share: number }[]; srm_ranges: { range: string; count: number }[];
};

export type Crumb = { kind: "department" | "course" | "coordinator" | "faculty" | "section" | "offering"; id: string; label: string };

export type Overview = {
  scope: { root: string; crumbs: Crumb[] };
  period: string;
  filters: ScopeFilters;
  generated_at: string;
  counts: { departments: number; courses: number; sections: number; offerings: number; students: number; faculty: number; coordinators: number; assessments: number };
  kpis: Kpis;
  trend: TrendPoint[];
  course_trends: { course_id: string; course_code: string; points: { key: string; name: string; mean: number | null }[] }[];
  comparisons: { courses: CompareRow[]; sections: CompareRow[]; faculty: CompareRow[]; semesters: CompareRow[]; departments: CompareRow[] };
  heatmap: { columns: { key: string; name: string }[]; rows: { id: string; label: string; values: Record<string, number | null> }[] };
  attention_matrix: { rules: string[]; rows: { id: string; label: string; cohort: number; values: Record<string, number> }[] };
  heatmap_rows: "sections" | "courses";
  students: Record<"top" | "bottom" | "borderline" | "improving" | "declining" | "persistently_low", StudentEntry[]>;
  activity: {
    imports: { id: string; file_name: string; status: string; offering: string | null; offering_id: string; by: string | null; at: string; created: number | null; updated: number | null }[];
    import_counts: Record<string, number>; confirmed_imports: number; interventions: number;
    audit: { action: string; entity: string; actor: string | null; at: string }[];
  };
};

export type OfferingRow = CompareRow & {
  course_id: string; course_code: string; course_name: string; section_id: string; section_name: string;
  term_code: string; term_name: string; semester: string | null; published_assessments: number;
  faculty: { id: string; name: string }[]; coordinators: { id: string; name: string }[];
};

export type AttentionItem = {
  id: string; rule_code: string; severity: "high" | "medium" | "low"; status: string; message: string;
  actual_value: number; actual_unit: string; threshold_value: number | null; assessments: string[]; computed_at: string;
  student: { id: string; register_number: string; name: string }; offering_id: string; offering: string; faculty: string[];
};

export type InterventionItem = {
  id: string; offering_id: string; offering: string; kind: string; status: string; after_sequence_no: number;
  recorded_on: string | null; note: string | null; students: { id: string; register_number: string; name: string }[];
  recorded_by: string | null; created_at: string;
};

export type IssueRead = { level: "error" | "warning" | "info"; code: string; message: string; column: string | null };

export type ImportPreview = {
  batch: {
    id: string; offering_id: string; assessment_id: string | null; status: "previewed" | "committed" | "discarded";
    file_name: string; file_type: string; total_rows: number; summary: Record<string, number | boolean>;
    created_at: string; expires_at: string; committed_at: string | null; source_metadata: Record<string, unknown>;
  };
  summary: Record<string, number | boolean>;
  file_issues: IssueRead[];
  columns: { header: string; role: string; assessment_id: string | null; assessment_name: string | null; mapped_by: string; issues: IssueRead[] }[];
  rows: {
    row: number; register_number: string | null; student_id: string | null; student_name: string | null; excluded: boolean; issues: IssueRead[];
    cells: { column: string; assessment_name: string | null; raw: string | null; value: string | null; fixed: boolean; status: string | null; score: number | null; change: string | null; issues: IssueRead[] }[];
  }[];
  missing_students: { id: string; register_number: string; full_name: string }[];
};

export type TlpFile = {
  file_name: string;
  status: "valid" | "warning" | "error" | "rejected" | "duplicate" | "skipped" | "confirmed" | "discarded";
  message: string | null; batch_id: string | null; offering_id: string | null; offering_label: string | null;
  section_name: string | null; assessment_id: string | null; assessment_name: string | null; routed_by: string | null;
  source_metadata: Record<string, unknown>; summary: Record<string, number | boolean>; issues: IssueRead[];
};
export type TlpUpload = { group_id: string; files: TlpFile[]; counts: Record<string, number> };

export type UserRead = {
  id: string; email: string; full_name: string; role: Role; department_id: string | null; employee_code: string | null;
  designation: string | null; is_active: boolean; last_login_at: string | null; created_at: string;
};
export type Department = { id: string; code: string; name: string };
export type Term = { id: string; code: string; name: string; academic_year: string; start_date: string; end_date: string; is_current: boolean; semester: "ODD" | "EVEN" | null };
export type CourseRead = { id: string; code: string; name: string; credits: number | null; course_type: string | null; department: Department; coordinators: { id: string; full_name: string; email: string }[] };
export type SectionRead = { id: string; name: string; batch_year: number; program: string | null; department: Department };
export type OfferingRead = {
  id: string; course: { id: string; code: string; name: string; department_id: string; course_type: string | null };
  term: { id: string; code: string; name: string; academic_year: string; is_current: boolean; semester: string | null };
  section: { id: string; name: string; batch_year: number; department_id: string };
  pass_percent: number; faculty: { id: string; full_name: string; email: string }[];
};
export type AssessmentDetail = {
  id: string; offering_id: string; name: string; assessment_type: string; assessment_date: string | null; max_marks: number; weightage: number;
  sequence_no: number; is_published: boolean; result_counts: { present: number; absent: number; exempt: number; missing: number; total?: number };
};
export type StudentRead = {
  id: string; register_number: string; full_name: string; email: string | null; department: Department; batch_year: number;
  current_section: { id: string; name: string; batch_year: number } | null; is_active: boolean;
};
export type AuditRow = { id: string; actor_id: string | null; entity: string; entity_id: string; action: string; old_value: unknown; new_value: unknown; offering_id: string | null; created_at: string };
export type ReportHistory = { id: string; title: string; scope: Record<string, string | null>; kind: string; format: string; file_name: string; size_bytes: number; created_at: string };
