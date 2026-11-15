import { defineConfig, devices } from "@playwright/test";

/**
 * Browser end-to-end tests against a RUNNING stack (they do not start one):
 *
 *   E2E_WEB=http://localhost:3010 E2E_API=http://localhost:8010 \
 *   E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... npm run test:e2e
 *
 * Use a throwaway stack (docs/TESTING_AND_VERIFICATION.md). The global setup creates its own
 * department, people, classes and marks with a unique code, so runs never touch other data.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts/,
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: process.env.E2E_WEB,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, testIgnore: /mobile\.spec\.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
});
