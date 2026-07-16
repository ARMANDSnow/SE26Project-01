import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile-390",
      use: { ...devices["iPhone 13"], browserName: "chromium", viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: [
    {
      command: "DATABASE_PATH=/tmp/paperwiki-iter11-e2e.sqlite3 UPLOAD_DIR=/tmp/paperwiki-iter11-e2e-uploads .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/api/health",
      timeout: 30_000,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --port 5173",
      url: "http://127.0.0.1:5173",
      timeout: 30_000,
      reuseExistingServer: false,
    },
  ],
})
