import fs from "node:fs";
import { expect, type Page, type ConsoleMessage } from "@playwright/test";
import { STATE_FILE, type E2EState, type Person } from "./global-setup";

export function state(): E2EState {
  return JSON.parse(fs.readFileSync(STATE_FILE, "utf8")) as E2EState;
}

const ROLE_LABEL: Record<Person["role"], string> = {
  FACULTY: "Faculty",
  COURSE_COORDINATOR: "Course Coordinator",
  ACADEMIC_HEAD: "Academic Head",
  HOD: "HOD",
  ADMIN: "Administrator",
};

/** The role option on the sign-in page for a role (exact label). */
export function roleOption(page: Page, role: Person["role"]) {
  return page.getByRole("radio", { name: ROLE_LABEL[role], exact: true });
}

/**
 * Sign in through the real form, the way a person does: email, password, the role selector, then
 * Sign in. `as` overrides the role chosen (to test a mismatch) and `password` the password. When
 * sign-in succeeds the welcome tour is skipped so it never covers what a test clicks; tests of the
 * tour itself use `keepTour`.
 */
export async function signIn(
  page: Page,
  user: Pick<Person, "email" | "password" | "role">,
  next?: string,
  options: { as?: Person["role"]; password?: string; keepTour?: boolean } = {},
) {
  await page.goto(next ? `/login?next=${encodeURIComponent(next)}` : "/login");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill(options.password ?? user.password);
  await roleOption(page, options.as ?? user.role).check();
  await page.getByRole("button", { name: /sign in/i }).click();
  const outcome = await Promise.race([
    page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 20_000 }).then(() => "in" as const),
    page.locator(".notice-error").waitFor({ timeout: 20_000 }).then(() => "error" as const),
  ]);
  if (outcome === "in" && !options.keepTour) await skipTour(page);
}

/** Close the welcome tour if it appears (it does on a user's first visit on a fresh browser). */
export async function skipTour(page: Page) {
  const skip = page.getByRole("button", { name: "Skip tour" });
  await skip.waitFor({ timeout: 6_000 }).then(() => skip.click()).catch(() => undefined);
}

/**
 * Collects what a person would notice went wrong: uncaught exceptions, console errors and
 * failed API calls. Expected failures (a deliberate 404) are passed in as allowed.
 */
export function watch(page: Page) {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m: ConsoleMessage) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) problems.push(`console: ${m.text()}`);
  });
  page.on("response", (r) => {
    if (r.url().includes("/api/") && r.status() >= 400) problems.push(`http ${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`);
  });
  return {
    problems,
    expectClean(allowed: RegExp[] = []) {
      expect(problems.filter((p) => !allowed.some((a) => a.test(p)))).toEqual([]);
    },
  };
}
