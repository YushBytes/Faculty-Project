/**
 * The teacher's import, end to end in the browser: choose the class, upload a plain CSV, see
 * every problem, map an unrecognised column, exclude a bad row, confirm, and find exactly the
 * previewed marks in the class (checked against the API as well as on screen).
 */
import { expect, test } from "@playwright/test";
import { signIn, state, watch } from "./helpers";

test("CSV import: preview, map, exclude, confirm, and the class shows the marks", async ({ page }) => {
  test.setTimeout(120_000);
  const s = state();
  const w = watch(page);
  const [a, b, c, d] = s.studentsA;
  // "Cycle Test 2" names no assessment (the class has CT1 and CT2): a column-level error.
  // Row 5 is above the maximum of 50: a cell-level error. A blank becomes absent, never 0.
  const csv = [
    "Register No,Name,Cycle Test 2",
    `${a.register_number},${a.full_name},41`,
    `${b.register_number},${b.full_name},0`,
    `${c.register_number},${c.full_name},`,
    `${d.register_number},${d.full_name},55`,
  ].join("\n");

  await signIn(page, s.facultyA.email, s.facultyA.password, `/import?offering_id=${s.classA}`);
  await expect(page.getByRole("heading", { level: 1, name: "Import TLP marks" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/Uploading into 21E/)).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles({ name: "ct2-marks.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: /Upload and validate 1 file/ }).click();

  const fileRow = page.locator(".file-row").filter({ hasText: "ct2-marks.csv" });
  await expect(fileRow.getByText("Errors", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Confirm 0 files/ })).toBeDisabled();
  await fileRow.getByRole("button", { name: "Review" }).click();

  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText("“Cycle Test 2”")).toBeVisible();
  await drawer.getByLabel("Assessment for column Cycle Test 2").selectOption({ label: "CT2 (max 50)" });
  await drawer.getByRole("button", { name: "Map column" }).click();
  await expect(drawer.getByText("→ CT2")).toBeVisible();

  const bad = drawer.locator(".card").filter({ hasText: d.register_number });
  await expect(bad).toContainText(/above|maximum/i);
  await bad.getByRole("button", { name: "Exclude row" }).click();
  await expect(bad.getByRole("button", { name: "Include" })).toBeVisible();
  await expect(drawer.getByText(/0 errors/)).toBeVisible();
  await drawer.getByRole("button", { name: "Done" }).click();

  await page.getByRole("button", { name: /Confirm 1 file/ }).click();
  await expect(fileRow.getByText("Confirmed", { exact: true })).toBeVisible();

  // What was written, from the API: exactly the three previewed rows, the 55 excluded.
  const token = await page.evaluate(async () => (await (await fetch("/api/session/refresh", { method: "POST" })).json()).access_token as string);
  const grid = await (await page.request.get(`/api/v1/assessments/${s.assessmentB}/results`, { headers: { authorization: `Bearer ${token}` } })).json();
  const byReg = Object.fromEntries(grid.rows.map((r: { student: { register_number: string }; state: string; result: { score: number | null } | null }) => [r.student.register_number, r]));
  expect(byReg[a.register_number].state).toBe("present");
  expect(Number(byReg[a.register_number].result.score)).toBe(41);
  expect(byReg[b.register_number].state).toBe("present");
  expect(Number(byReg[b.register_number].result.score)).toBe(0);
  expect(byReg[c.register_number].state).toBe("absent");
  expect(byReg[c.register_number].result.score).toBeNull();
  expect(byReg[d.register_number].state).toBe("missing");

  // And on screen, in the class's marks grid.
  await fileRow.getByRole("link", { name: "Open class" }).click();
  await page.getByRole("tab", { name: "Marks" }).click();
  await expect(page.getByRole("columnheader", { name: /CT2/ })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: a.full_name })).toContainText("41");
  w.expectClean([/http 422 POST \/api\/v1\/imports\/.*\/confirm/]);
});

test("a file that cannot be read is refused with a reason and writes nothing", async ({ page }) => {
  const s = state();
  await signIn(page, s.facultyA.email, s.facultyA.password, `/import?offering_id=${s.classA}`);
  await expect(page.getByRole("heading", { level: 1, name: "Import TLP marks" })).toBeVisible({ timeout: 20_000 });
  await page.locator('input[type="file"]').setInputFiles({ name: "broken.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("PK\u0003\u0004 not really a workbook") });
  await page.getByRole("button", { name: /Upload and validate 1 file/ }).click();
  const row = page.locator(".file-row").filter({ hasText: "broken.xlsx" });
  await expect(row.getByText("Rejected")).toBeVisible();
  await expect(row).toContainText(/cannot be read|not a valid|could not|unreadable|corrupt/i);
});
