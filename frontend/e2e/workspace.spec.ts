/**
 * Role workspaces: grouped navigation per role, quick actions that open real pages, meaningful
 * empty states, the "How it works" notes and the welcome tour (skip, remember, replay).
 */
import { expect, test, type Page } from "@playwright/test";
import { signIn, state, watch } from "./helpers";

const GROUPS = ["Home", "Academic Management", "Performance Intelligence", "Student Support", "Data & Imports", "Reports", "Administration"];

async function groupLabels(page: Page) {
  return page.locator(".sidebar .nav-label").allInnerTexts();
}

test("the Administrator sees every group, and its quick actions all open working pages", async ({ page }) => {
  test.setTimeout(120_000);
  const s = state();
  await signIn(page, s.admin);
  expect((await groupLabels(page)).map((l) => l.toLowerCase())).toEqual(GROUPS.map((g) => g.toLowerCase()));
  const actions = page.getByRole("navigation", { name: "Quick actions" }).getByRole("link");
  await expect(actions).toHaveText([/Manage users/, /Departments/, /Institution analytics/, /Imports/, /Audit log/]);
  const hrefs = await actions.evaluateAll((links) => links.map((a) => a.getAttribute("href")!));
  for (const href of hrefs) {
    const w = watch(page);
    await page.goto(href);
    await expect(page.getByRole("heading", { level: 1 }), href).toBeVisible();
    await expect(page.getByText(/Could not load this view|Not found or not in your scope/)).toHaveCount(0);
    w.expectClean();
    page.removeAllListeners("response"); page.removeAllListeners("console"); page.removeAllListeners("pageerror");
  }
  // The existing dashboard is still there under the quick actions.
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Welcome back");
  await expect(page.getByText("What is happening across the institution?")).toBeVisible();
});

test("faculty see a focused menu and their quick actions open their own pages", async ({ page }) => {
  const s = state();
  await signIn(page, s.facultyA);
  const labels = (await groupLabels(page)).map((l) => l.toLowerCase());
  expect(labels).not.toContain("administration");
  expect(labels).toContain("student support");
  const actions = page.getByRole("navigation", { name: "Quick actions" }).getByRole("link");
  await expect(actions.first()).toHaveText(/My classes/);
  await actions.filter({ hasText: "Upload TLP" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Import TLP marks" })).toBeVisible();
  await page.goto("/dashboard");
  await actions.filter({ hasText: "My classes" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "My classes" })).toBeVisible();
  await expect(page.locator("main")).toContainText(`S1${s.run}`);
});

test("the HOD's quick actions include their department and its overview opens", async ({ page }) => {
  const s = state();
  await signIn(page, s.hod);
  const overview = page.getByRole("navigation", { name: "Quick actions" }).getByRole("link", { name: /Department overview/ });
  await expect(overview).toHaveAttribute("href", new RegExp(`/departments/${s.departmentId}`));
  await overview.click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(`Browser tests ${s.run}`);
  await expect(page.getByText(/Not found or not in your scope/)).toHaveCount(0);
  expect((await groupLabels(page)).map((l) => l.toLowerCase())).toContain("administration"); // People, Audit
});

test("a faculty member with no classes gets an explanation, not an empty table", async ({ page }) => {
  const s = state();
  await signIn(page, s.facultyC, "/classes");
  await expect(page.getByRole("heading", { level: 1, name: "My classes" })).toBeVisible();
  await expect(page.getByText("No classes assigned to you in this period")).toBeVisible();
  await expect(page.getByText(/will appear here when they are assigned to you/)).toBeVisible();
  await expect(page.getByText("Nothing to show yet")).toHaveCount(0);
});

test("Attention and Analytics explain how they work, collapsed by default", async ({ page }) => {
  const s = state();
  await signIn(page, s.facultyA, "/attention");
  const how = page.locator("details.how-it-works");
  await expect(how).toBeVisible();
  await expect(how.locator(".how-body")).toBeHidden();
  await how.locator("summary").click();
  await expect(how.locator(".how-body")).toContainText("any High rule fires, or at least two Medium rules");
  await page.goto("/analytics");
  await page.locator("details.how-it-works summary").click();
  await expect(page.locator("details.how-it-works .how-body")).toContainText("Nothing here predicts results");
});

test("the welcome tour: role-specific, skippable, remembered, and replayable from Settings", async ({ page }) => {
  const s = state();
  await signIn(page, s.facultyB, undefined, { keepTour: true });
  const tour = page.getByRole("dialog", { name: "Your classes at a glance" });
  await expect(tour).toBeVisible();
  await expect(tour).toContainText("1 of 5");
  // It never blocks the page: the sidebar still works while it is open.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Attention" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Students needing attention" })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("dialog", { name: "My classes" })).toBeVisible();
  await expect(page.getByRole("dialog")).not.toContainText(/People|Audit log/);
  await page.getByRole("button", { name: "Skip tour" }).click();
  await expect(page.locator("section.tour")).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator("section.tour")).toHaveCount(0); // remembered
  await page.goto("/settings");
  await page.getByRole("button", { name: "Replay tour" }).click();
  await expect(page.getByRole("dialog", { name: "Your classes at a glance" })).toBeVisible();
  for (let i = 0; i < 4; i += 1) await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.locator("section.tour")).toHaveCount(0);
});
