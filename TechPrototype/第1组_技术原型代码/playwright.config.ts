import { defineConfig, devices } from "@playwright/test"

const backendPort = process.env.E2E_BACKEND_PORT ?? "8000"
const frontendPort = process.env.E2E_FRONTEND_PORT ?? "5173"
const databasePath = process.env.E2E_DATABASE_PATH ?? "/tmp/paperwiki-iter15-e2e.sqlite3"
const uploadDir = process.env.E2E_UPLOAD_DIR ?? "/tmp/paperwiki-iter15-e2e-uploads"

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop-1440", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "tablet-1024", use: { ...devices["Desktop Chrome"], viewport: { width: 1024, height: 768 } } },
    {
      name: "mobile-390",
      use: { ...devices["iPhone 13"], browserName: "chromium", viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: [
    {
      command: `DATABASE_PATH=${databasePath} UPLOAD_DIR=${uploadDir} .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port ${backendPort}`,
      url: `http://127.0.0.1:${backendPort}/api/health`,
      timeout: 30_000,
      reuseExistingServer: false,
    },
    {
      command: `E2E_BACKEND_PORT=${backendPort} npm run dev -- --port ${frontendPort}`,
      url: `http://127.0.0.1:${frontendPort}`,
      timeout: 30_000,
      reuseExistingServer: false,
    },
  ],
})
