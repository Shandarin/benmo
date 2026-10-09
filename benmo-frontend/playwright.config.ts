import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "node tests/mock-api.mjs",
      url: "http://127.0.0.1:4010/health/ready",
      reuseExistingServer: false,
    },
    {
      command:
        "cross-env PORT=3100 BENMO_API_BASE_URL=http://127.0.0.1:4010 SITE_URL=http://127.0.0.1:3100 npm run dev",
      url: "http://127.0.0.1:3100/healthz",
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["iPhone 13"], browserName: "chromium" } },
  ],
});
