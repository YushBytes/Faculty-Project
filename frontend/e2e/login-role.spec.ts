/**
 * The sign-in role selector: five checkbox-style options, one choice at a time, required by the
 * website, checked by the server against the stored role, and never a source of permissions.
 */
import { expect, test } from "@playwright/test";
import { roleOption, signIn, state } from "./helpers";

const MISMATCH = "The selected role does not match your account. Please choose your assigned role.";

test("five role options, one at a time, and Sign in waits for a choice", async ({ page }) => {
  await page.goto("/login");
  const group = page.getByRole("group", { name: "Your role" });
  await expect(group.getByRole("radio")).toHaveCount(5);
  for (const label of ["Faculty", "Course Coordinator", "Academic Head", "HOD", "Administrator"]) {
    await expect(group.getByRole("radio", { name: label, exact: true })).toBeVisible();
  }
  await page.getByLabel("Email").fill("someone@example.edu");
  await page.getByLabel("Password", { exact: true }).fill("anything-at-all");
  await expect(page.getByRole("button", { name: /sign in/i })).toBeDisabled();
  await roleOption(page, "HOD").check();
  await roleOption(page, "FACULTY").check();
  await expect(roleOption(page, "FACULTY")).toBeChecked();
  await expect(roleOption(page, "HOD")).not.toBeChecked();
  await expect(group.locator("input:checked")).toHaveCount(1);
  await expect(page.getByRole("button", { name: /sign in/i })).toBeEnabled();
  // Keyboard: arrow keys move the single choice, like any radio group.
  await roleOption(page, "FACULTY").focus();
  await page.keyboard.press("ArrowRight");
  await expect(roleOption(page, "COURSE_COORDINATOR")).toBeChecked();
});

test("the right role signs in; the stored role, not the choice, shapes the workspace", async ({ page }) => {
  const s = state();
  await signIn(page, s.hod);
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.locator(".role-pill")).toHaveText("Head of Department");
});

test("a correct password with the wrong role is refused with the role message and no session", async ({ page }) => {
  const s = state();
  await signIn(page, s.facultyA, undefined, { as: "ADMIN" });
  await expect(page.locator(".notice-error")).toHaveText(MISMATCH);
  await expect(page).toHaveURL(/\/login/);
  const session = await page.request.post("/api/session/refresh");
  expect(session.status()).toBe(204); // no refresh cookie was set: nothing to restore
  await page.goto("/admin/users");
  await expect(page).toHaveURL(/\/login\?next=/);
});

test("a wrong password keeps the generic message, whatever role is chosen", async ({ page }) => {
  const s = state();
  await signIn(page, s.facultyA, undefined, { password: "definitely-wrong", as: "ADMIN" });
  await expect(page.locator(".notice-error")).toHaveText(/do not match an active account/);
  await expect(page.locator(".notice-error")).not.toHaveText(MISMATCH);
});

test("the website's sign-in route requires a role and ignores smuggled fields", async ({ request }) => {
  const s = state();
  const base = { email: s.facultyA.email, password: s.facultyA.password };
  const missing = await request.post("/api/session/login", { data: base });
  expect(missing.status()).toBe(422);
  const unknown = await request.post("/api/session/login", { data: { ...base, role: "SUPERUSER" } });
  expect(unknown.status()).toBe(422);
  const malformed = await request.post("/api/session/login", { data: { ...base, role: ["ADMIN"] } });
  expect(malformed.status()).toBe(422);
  const escalate = await request.post("/api/session/login", { data: { ...base, role: "ADMIN" } });
  expect(escalate.status()).toBe(401);
  expect((await escalate.json()).error.code).toBe("role_mismatch");
  expect(await escalate.text()).not.toContain("access_token");
  // Extra fields are dropped before the API; the stored role still decides.
  const smuggled = await request.post("/api/session/login", { data: { ...base, role: "FACULTY", is_admin: true, claims: { role: "ADMIN" } } });
  expect(smuggled.status()).toBe(200);
  const token = (await smuggled.json()).access_token as string;
  const users = await request.get("/api/v1/users", { headers: { authorization: `Bearer ${token}` } });
  expect(users.status()).toBe(403);
});

test("the API keeps working without a role (scripts and tools)", async ({ request }) => {
  const s = state();
  const api = s.api;
  const ok = await request.post(`${api}/api/v1/auth/login`, { data: { email: s.facultyA.email, password: s.facultyA.password } });
  expect(ok.status()).toBe(200);
  const mismatch = await request.post(`${api}/api/v1/auth/login`, { data: { email: s.facultyA.email, password: s.facultyA.password, role: "HOD" } });
  expect(mismatch.status()).toBe(401);
  expect((await mismatch.json()).error.code).toBe("role_mismatch");
  const anonymous = await request.get(`${api}/api/v1/users`);
  expect(anonymous.status()).toBe(401);
});
