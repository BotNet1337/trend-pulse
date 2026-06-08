import path from "node:path"
import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"

import { defineConfig, devices } from "@playwright/test"
import { config as loadEnv } from "dotenv"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
loadEnv({ path: path.resolve(__dirname, ".env") })

const FRONTEND_URL = process.env.FRONTEND_URL ?? "https://app.postbridge.local"
const STORAGE_STATE_PATH = path.resolve(
  __dirname,
  "tests/visual/.auth/state.json",
)
const HAS_STORAGE = existsSync(STORAGE_STATE_PATH)

export default defineConfig({
  testDir: "./tests/visual",
  snapshotDir: "./tests/visual/__screenshots__",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [["html", { outputFolder: "playwright-report", open: "never" }]],
  globalSetup: "./tests/visual/global-setup.ts",
  use: {
    baseURL: FRONTEND_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    ignoreHTTPSErrors: true,
    storageState: HAS_STORAGE ? STORAGE_STATE_PATH : undefined,
    contextOptions: {
      reducedMotion: "reduce",
    },
  },
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.02,
    },
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
