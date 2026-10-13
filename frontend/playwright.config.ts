import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/*
 * End-to-end tests run against an isolated stack:
 *   backend  → :8001, fresh SQLite database in .e2e/, scheduler off, synthetic demo data only (no network)
 *   frontend → :3001, own build dir (.next-e2e), proxying /api to :8001
 * so they never touch development data or the dev servers on :3000/:8000.
 */
const root = path.resolve(__dirname, "..");
const e2eDir = path.join(__dirname, ".e2e").replace(/\\/g, "/");
// Fresh database per run. Only in the main process: workers also load this file and must not wipe it mid-run.
if (!process.env.TEST_WORKER_INDEX) {
  fs.rmSync(path.join(__dirname, ".e2e"), { recursive: true, force: true });
  fs.mkdirSync(path.join(__dirname, ".e2e", "uploads"), { recursive: true });
}
const python = process.platform === "win32" ? path.join(root, "backend", ".venv", "Scripts", "python.exe") : path.join(root, "backend", ".venv", "bin", "python");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 20_000 }, // first visit to a page compiles it in dev mode
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3001",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 900 } }, testIgnore: /mobile.spec.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
    { name: "tablet", use: { ...devices["Desktop Chrome"], viewport: { width: 768, height: 1024 } }, testMatch: /mobile\.spec\.ts/, grepInvert: /mobile menu/ },
  ],
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --host 127.0.0.1 --port 8001`,
      cwd: path.join(root, "backend"),
      url: "http://127.0.0.1:8001/api/health",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        SCAMSHIELD_ENV: "development",
        SCAMSHIELD_DATABASE_URL: `sqlite:///${e2eDir}/e2e.db`,
        SCAMSHIELD_UPLOAD_DIR: `${e2eDir}/uploads`,
        SCAMSHIELD_SCHEDULER_ENABLED: "false",
        SCAMSHIELD_AUTH_RATE_LIMIT_ATTEMPTS: "1000",
        SCAMSHIELD_FRONTEND_ORIGIN: "http://localhost:3001",
      },
    },
    {
      command: "npx next dev -p 3001",
      cwd: __dirname,
      url: "http://localhost:3001",
      reuseExistingServer: false,
      timeout: 180_000,
      env: { NEXT_DIST_DIR: ".next-e2e", BACKEND_URL: "http://127.0.0.1:8001", NEXT_TELEMETRY_DISABLED: "1" },
    },
  ],
});
