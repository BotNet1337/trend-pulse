import path from "node:path"
import { fileURLToPath } from "node:url"

import { defineConfig, devices } from "@playwright/test"
import { config as loadEnv } from "dotenv"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
loadEnv({ path: path.resolve(__dirname, ".env") })

// Edge nginx base URL — smoke e2e runs against the real stack behind nginx.
// Override with FRONTEND_URL env if needed for non-standard setups.
const HTTP_PORT = process.env.HTTP_PORT ?? "80"
const BASE_URL = process.env.FRONTEND_URL ?? `http://localhost:${HTTP_PORT}`

export default defineConfig({
  // Smoke e2e tests directory
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: BASE_URL,
    // TASK-032 CSRF: the backend rejects cookie-auth mutations without an Origin
    // header. A real browser sends Origin on same-origin POST/PATCH/DELETE, but
    // Playwright's APIRequestContext (page.request.*) does not — set it so the
    // request context mirrors the browser. new URL().origin normalizes the :80
    // default port away → matches the backend allow-list (http://localhost).
    extraHTTPHeaders: {
      Origin: new URL(BASE_URL).origin,
    },
    // Artifacts on failure
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
})
