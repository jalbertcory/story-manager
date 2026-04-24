import { defineConfig, devices } from "@playwright/test";

const isCi = !!process.env.CI;
const backendPort = process.env.PLAYWRIGHT_BACKEND_PORT || "18000";
const frontendPort = process.env.PLAYWRIGHT_FRONTEND_PORT || "15173";
const backendUrl = `http://127.0.0.1:${backendPort}`;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;

/**
 * See https://playwright.dev/docs/test-configuration
 */
const webServer = isCi
  ? undefined
  : [
      {
        command:
          `zsh -lc 'export PYTHONPATH=backend && .venv/bin/alembic -c backend/alembic.ini upgrade head && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}'`,
        url: backendUrl,
        cwd: "..",
        reuseExistingServer: true,
        timeout: 120 * 1000,
      },
      {
        command: `VITE_API_TARGET=${backendUrl} npm run dev -- --host 127.0.0.1 --port ${frontendPort} --strictPort`,
        url: frontendUrl,
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
    baseURL:
      process.env.PLAYWRIGHT_BASE_URL ||
      (isCi ? "http://localhost:8000" : frontendUrl),

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
