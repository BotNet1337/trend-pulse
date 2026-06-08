import path from "node:path"
import { fileURLToPath } from "node:url"

import { test, expect, type Page } from "@playwright/test"

import { requireTestCredentials } from "./fixtures/auth"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const DESIGN_PATH = path.resolve(
  HERE,
  "../../../../design/pages/workspace/index.html",
)
const DESIGN_URL = `file://${DESIGN_PATH}`

const designFrame = (label: string) => `ds-frame[label="${label}"]`

const captureDesignFrame = async (
  page: Page,
  label: string,
  fileName: string,
): Promise<void> => {
  await page.goto(DESIGN_URL)
  const frame = page.locator(designFrame(label))
  await frame.waitFor({ state: "attached", timeout: 5000 })
  await frame.scrollIntoViewIfNeeded()
  await expect(frame).toHaveScreenshot(fileName)
}

const skipUnlessSignedIn = async () => {
  const creds = requireTestCredentials()
  test.skip(
    !creds,
    "TEST_EMAIL / TEST_PASSWORD not set — skipping live frontend capture.",
  )
}

test.describe("workspace · selector", () => {
  test("design frame: Selector · 1280 × 800", async ({ page }) => {
    await captureDesignFrame(page, "Selector · 1280 × 800", "selector-design.png")
  })

  test("frontend page: /workspaces", async ({ page }) => {
    await skipUnlessSignedIn()
    await page.goto("/workspaces")
    await page.waitForSelector('[data-testid="create-workspace-card"]', {
      timeout: 10_000,
    })
    await expect(page).toHaveScreenshot("selector-frontend.png", {
      fullPage: false,
    })
  })
})

test.describe("workspace · create modal", () => {
  test("design frame: Create workspace", async ({ page }) => {
    await captureDesignFrame(page, "Create workspace", "create-design.png")
  })

  test("frontend modal: open create dialog", async ({ page }) => {
    await skipUnlessSignedIn()
    await page.goto("/workspaces")
    await page.click('[data-testid="create-workspace-card"]')
    const dialog = page.locator('[data-testid="create-workspace-dialog"]')
    await dialog.waitFor({ state: "visible" })
    await expect(dialog).toHaveScreenshot("create-frontend.png")
  })
})

test.describe("workspace · edit modal", () => {
  test("design frame: Edit workspace", async ({ page }) => {
    await captureDesignFrame(page, "Edit workspace", "edit-design.png")
  })

  test("frontend modal: open edit dialog", async ({ page }) => {
    await skipUnlessSignedIn()
    await page.goto("/workspaces")
    await page.locator('[data-testid="workspace-card"]').first().hover()
    await page
      .locator('[data-testid="workspace-card"] button[aria-label="Workspace actions"]')
      .first()
      .click()
    await page.getByRole("menuitem", { name: "Edit" }).click()
    const dialog = page.locator('[data-testid="edit-workspace-dialog"]')
    await dialog.waitFor({ state: "visible" })
    await expect(dialog).toHaveScreenshot("edit-frontend.png")
  })
})

test.describe("workspace · delete modal", () => {
  test("design frame: Delete workspace · confirm", async ({ page }) => {
    await captureDesignFrame(
      page,
      "Delete workspace · confirm",
      "delete-design.png",
    )
  })

  test("frontend modal: open delete dialog", async ({ page }) => {
    await skipUnlessSignedIn()
    await page.goto("/workspaces")
    await page.locator('[data-testid="workspace-card"]').first().hover()
    await page
      .locator('[data-testid="workspace-card"] button[aria-label="Workspace actions"]')
      .first()
      .click()
    await page.getByRole("menuitem", { name: "Delete" }).click()
    const dialog = page.locator('[data-testid="delete-workspace-dialog"]')
    await dialog.waitFor({ state: "visible" })
    await expect(dialog).toHaveScreenshot("delete-frontend.png")
  })
})

test.describe("workspace · switcher dropdown", () => {
  test("design frame: Workspace switcher · open", async ({ page }) => {
    await captureDesignFrame(
      page,
      "Workspace switcher · open",
      "switcher-design.png",
    )
  })

  test("frontend dropdown: open switcher", async ({ page }) => {
    await skipUnlessSignedIn()
    await page.goto("/workspaces")
    const card = page.locator('[data-testid="workspace-card"]').first()
    await card.click()
    await page.waitForLoadState("networkidle")
    const switcher = page.locator('[data-testid="workspace-switcher"] button').first()
    await switcher.click()
    const menu = page.locator('[data-testid="workspace-switcher"] [role="menu"]')
    await menu.waitFor({ state: "visible" })
    await expect(menu).toHaveScreenshot("switcher-frontend.png")
  })
})

test.describe("workspace · avatar menu", () => {
  test("design frame: Avatar · open", async ({ page }) => {
    await captureDesignFrame(page, "Avatar · open", "avatar-design.png")
  })

  test("frontend dropdown: open avatar menu", async ({ page }) => {
    await skipUnlessSignedIn()
    await page.goto("/workspaces")
    await page.click('[data-testid="avatar-pill-trigger"]')
    const menu = page.locator('[data-testid="avatar-menu"]')
    await menu.waitFor({ state: "visible" })
    await expect(menu).toHaveScreenshot("avatar-frontend.png")
  })
})
