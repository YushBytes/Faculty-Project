/**
 * Creates the data the browser tests use, through the API, with a unique code per run:
 *
 *   department E2E<run>, one course, sections S1/S2, class A (faculty A) and class B
 *   (faculty B), 8 students in class A with marks for one published assessment, 4 in class B.
 *
 * Writes e2e/.state.json (gitignored) for the specs. Fails loudly when the stack or the
 * credentials are missing: an unconfigured run is an error, not a skipped test.
 */
import fs from "node:fs";
import path from "node:path";
import { randomBytes } from "node:crypto";

export type E2EState = {
  web: string;
  api: string;
  run: string;
  admin: { email: string; password: string };
  facultyA: { email: string; password: string; id: string };
  facultyB: { email: string; password: string; id: string };
  classA: string;
  classB: string;
  assessmentA: string;
  assessmentB: string;
  studentsA: { id: string; register_number: string; full_name: string }[];
  studentsB: { id: string; register_number: string; full_name: string }[];
};

export const STATE_FILE = path.join(__dirname, ".state.json");

function need(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Set ${name} (see playwright.config.ts). Browser tests need a running throwaway stack.`);
  return value.replace(/\/$/, "");
}

export default async function globalSetup() {
  const web = need("E2E_WEB");
  const api = need("E2E_API");
  const admin = { email: need("E2E_ADMIN_EMAIL"), password: need("E2E_ADMIN_PASSWORD") };
  const run = randomBytes(3).toString("hex").toUpperCase();
  const digits = String(parseInt(run, 16) % 100000).padStart(5, "0");

  async function call<T>(method: string, url: string, token: string | null, body?: unknown): Promise<T> {
    const response = await fetch(`${api}/api/v1${url}`, {
      method,
      headers: { ...(token ? { authorization: `Bearer ${token}` } : {}), ...(body !== undefined ? { "content-type": "application/json" } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    if (!response.ok) throw new Error(`${method} ${url} -> ${response.status}: ${text.slice(0, 300)}`);
    return (text ? JSON.parse(text) : undefined) as T;
  }
  const login = async (email: string, password: string) => (await call<{ access_token: string }>("POST", "/auth/login", null, { email, password })).access_token;

  const token = await login(admin.email, admin.password);
  const dept = await call<{ id: string }>("POST", "/departments", token, { code: `E2E${run}`, name: `Browser tests ${run}` });
  const terms = await call<{ items: { id: string; is_current: boolean }[] }>("GET", "/terms?limit=200", token);
  let term = terms.items.find((t) => t.is_current) ?? terms.items[0];
  if (!term) {
    term = await call("POST", "/terms", token, { code: "AY2025-26-EVEN", name: "Even Semester 2025-26", academic_year: "2025-26", start_date: "2026-01-01", end_date: "2026-06-30", is_current: true });
  }
  const course = await call<{ id: string }>("POST", "/courses", token, { department_id: dept.id, code: `21E${run}T`, name: `Browser Test Course ${run}` });
  const sections = [];
  for (const name of ["S1", "S2"]) sections.push(await call<{ id: string }>("POST", "/sections", token, { department_id: dept.id, name: `${name}${run}`, batch_year: 2024 }));

  const people: Record<string, { email: string; password: string; id: string }> = {};
  for (const key of ["a", "b"]) {
    const password = `E2e-${randomBytes(9).toString("base64url")}`;
    const email = `faculty.${key}.${run.toLowerCase()}@e2e.acadlytics.dev`;
    const user = await call<{ id: string }>("POST", "/users", token, { email, full_name: `E2E Faculty ${key.toUpperCase()} ${run}`, password, role: "FACULTY", department_id: dept.id });
    people[key] = { email, password, id: user.id };
  }
  const classA = await call<{ id: string }>("POST", "/offerings", token, { course_id: course.id, term_id: term.id, section_id: sections[0].id, faculty_ids: [people.a.id] });
  const classB = await call<{ id: string }>("POST", "/offerings", token, { course_id: course.id, term_id: term.id, section_id: sections[1].id, faculty_ids: [people.b.id] });

  const names = ["ANAND RAO", "BHAVNA SHETTY", "CHIRAG MEHTA", "DEEPA NAIR", "ESHAAN GUPTA", "FATIMA KHAN", "GAURAV JAIN", "HEMA PRASAD"];
  const rows = names.map((full_name, i) => ({ register_number: `RA24${digits}${String(i + 1).padStart(6, "0")}`, full_name, department_code: `E2E${run}`, batch_year: 2024, section: `S1${run}` }));
  rows.push(...["ISHA VERMA", "JAYANT DAS", "KIRAN BOSE", "LATA IYER"].map((full_name, i) => ({ register_number: `RA24${digits}${String(101 + i).padStart(6, "0")}`, full_name, department_code: `E2E${run}`, batch_year: 2024, section: `S2${run}` })));
  await call("POST", "/students/bulk", token, { rows });
  await call("POST", `/offerings/${classA.id}/enrollments/from-section`, token);
  await call("POST", `/offerings/${classB.id}/enrollments/from-section`, token);
  type Roster = { student: { id: string; register_number: string; full_name: string } }[];
  const studentsA = (await call<Roster>("GET", `/offerings/${classA.id}/students`, token)).map((r) => r.student);
  const studentsB = (await call<Roster>("GET", `/offerings/${classB.id}/students`, token)).map((r) => r.student);

  const tokenA = await login(people.a.email, people.a.password);
  const assessmentA = await call<{ id: string }>("POST", `/offerings/${classA.id}/assessments`, tokenA, { name: "CT1", assessment_type: "CT", max_marks: 50, weightage: 50, is_published: true });
  // Marks: a spread with one genuine zero, one absent and one with no row at all (missing).
  const marks = [45, 38, 24, 0, null, 30, 50];
  await call("PUT", `/assessments/${assessmentA.id}/results`, tokenA, {
    results: marks.map((score, i) => (score === null ? { student_id: studentsA[i].id, status: "absent" } : { student_id: studentsA[i].id, score })),
  });
  // A second, unpublished assessment that the browser import test fills in.
  const assessmentB = await call<{ id: string }>("POST", `/offerings/${classA.id}/assessments`, tokenA, { name: "CT2", assessment_type: "CT", max_marks: 50, weightage: 50 });

  const state: E2EState = {
    web, api, run, admin,
    facultyA: people.a, facultyB: people.b,
    classA: classA.id, classB: classB.id, assessmentA: assessmentA.id, assessmentB: assessmentB.id,
    studentsA, studentsB,
  };
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 1));
}
