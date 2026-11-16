import { expect, test } from "@playwright/test";
import { signIn, state, watch } from "./helpers";

test("faculty B cannot open faculty A's class or student, and sees only their own class", async ({ page }) => {
  const s = state();
  await signIn(page, s.facultyB.email, s.facultyB.password);
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 20_000 });

  await page.goto(`/classes/${s.classA}`);
  await expect(page.getByText("Not found or not in your scope")).toBeVisible();
  await page.goto(`/students/${s.studentsA[0].id}`);
  await expect(page.getByText(/Not found or not in your scope|Could not load/)).toBeVisible();

  await page.goto("/classes");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const main = page.locator("main");
  await expect(main).toContainText(`S2${s.run}`);
  await expect(main).not.toContainText(`S1${s.run}`);
  await page.goto("/students");
  await expect(main).toContainText(s.studentsB[0].full_name);
  await expect(main).not.toContainText(s.studentsA[0].full_name);
});

test("class reports download from the browser in all three formats", async ({ page }) => {
  const s = state();
  const w = watch(page);
  await signIn(page, s.facultyA.email, s.facultyA.password, `/classes/${s.classA}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Browser Test Course", { timeout: 20_000 });
  await page.getByRole("tab", { name: "Reports" }).click();
  const card = page.locator(".card").filter({ hasText: "Class summary" }).first();
  for (const [format, magic] of [["PDF", "%PDF-"], ["XLSX", "PK"], ["CSV", ""]] as const) {
    const download = page.waitForEvent("download");
    await card.getByRole("button", { name: format }).click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(new RegExp(`^class_summary-21E${s.run}T-\\d{4}-\\d{2}-\\d{2}\\.${format.toLowerCase()}$`));
    const stream = await file.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(chunk as Buffer);
    const body = Buffer.concat(chunks);
    expect(body.length).toBeGreaterThan(200);
    expect(body.subarray(0, magic.length).toString("latin1")).toBe(magic);
    if (format === "CSV") expect(body.toString("utf8")).not.toMatch(/NaN|Infinity/);
  }
  await expect(page.getByText("Report downloaded").first()).toBeVisible();
  w.expectClean();
});

test("an intervention is recorded from the attention list and appears in the class", async ({ page }) => {
  const s = state();
  await signIn(page, s.facultyA.email, s.facultyA.password, `/classes/${s.classA}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Browser Test Course", { timeout: 20_000 });
  await page.getByRole("tab", { name: /^Attention/ }).click();
  const flagged = page.getByRole("row").filter({ hasText: "DEEPA NAIR" }).first();
  await expect(flagged).toBeVisible();
  await flagged.getByRole("button", { name: "Intervene" }).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  const note = drawer.locator("textarea");
  if (await note.count()) await note.first().fill("Browser test: extra practice set");
  await drawer.getByRole("button", { name: /save|record/i }).click();
  await expect(page.getByText(/recorded|saved/i).first()).toBeVisible();
  await page.getByRole("tab", { name: "Interventions" }).click();
  await expect(page.getByRole("row").filter({ hasText: "DEEPA NAIR" })).toBeVisible();
  await expect(page.getByText(/never attributed to the intervention/)).toBeVisible();
});
