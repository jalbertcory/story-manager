import { defineConfig, devices } from "@playwright/test";

/**
 * See https://playwright.dev/docs/test-configuration
 */
const webServer = process.env.CI
  ? undefined
  : [
      {
        command:
          "zsh -lc 'export PYTHONPATH=backend && .venv/bin/alembic -c backend/alembic.ini upgrade head && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000'",
        url: "http://127.0.0.1:8000",
        cwd: "..",
        reuseExistingServer: true,
        timeout: 120 * 1000,
      },
      {
        command: "npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173",
        url: "http://127.0.0.1:5173",
        cwd: "..",
        reuseExistingServer: true,
        timeout: 120 * 1000,
      },
    ];

export default defineConfig({
  testDir: "./tests-e2e",
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Opt out of parallel tests on CI. */
  workers: process.env.CI ? 1 : undefined,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: "list",
  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: "http://localhost:5173",

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: "on-first-retry",
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer,
});
