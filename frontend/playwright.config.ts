import { defineConfig, devices } from "@playwright/test";

// End-to-end tests against the real stack: Vite on 5173 proxying to FastAPI on 8000.
// Start the backend first (see README); `webServer` reuses a running Vite or starts one.
// Chat tests also need a local Ollama, as the app does.
export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/.results",
  timeout: 180_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel: "chrome" } },
    { name: "mobile", use: { ...devices["Pixel 7"], channel: "chrome" }, grep: /@mobile/ },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
