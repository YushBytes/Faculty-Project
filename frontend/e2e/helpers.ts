import fs from "node:fs";
import { expect, type Page, type ConsoleMessage } from "@playwright/test";
import { STATE_FILE, type E2EState } from "./global-setup";

export function state(): E2EState {
  return JSON.parse(fs.readFileSync(STATE_FILE, "utf8")) as E2EState;
}

/** Sign in through the real form, the way a person does. */
export async function signIn(page: Page, email: string, password: string, next?: string) {
  await page.goto(next ? `/login?next=${encodeURIComponent(next)}` : "/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
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
