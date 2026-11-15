import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Unit tests of the browser-side client and helpers. Browser end-to-end tests are separate
// (Playwright, `npm run test:e2e`, under e2e/).
export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
    restoreMocks: true,
  },
});
