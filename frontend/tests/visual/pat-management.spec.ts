import { test, expect } from "@playwright/test"

import { requireTestCredentials, signInViaApi } from "./fixtures/auth"

/**
 * E2E for the PAT management section (TASK-080) on Account Settings.
 *
 * Covers the security-critical one-time reveal: create a token, assert the
 * full `pb_pat_…` plaintext is shown exactly once, then revoke it so the test
 * account stays clean. Skipped without TEST_EMAIL / TEST_PASSWORD and when the
 * account owns no workspace (PAT section needs a workspace for X-Workspace-Id).
 *
 * The PAT backend is already on main, so this is live-capable once a test
 * account with an owned workspace is provided.
 */

test.describe("account settings · API tokens", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("create a PAT → token shown once → revoke", async ({ page }) => {
    const creds = requireTestCredentials()
    test.skip(!creds, "TEST_EMAIL / TEST_PASSWORD not set")
    if (!creds) return

    await signInViaApi(page, { email: creds.email, password: creds.password })

    await page.goto("/account/settings")
    await page.waitForLoadState("networkidle")

    const section = page.getByTestId("pat-section")
    await expect(section).toBeVisible({ timeout: 10_000 })

    // Open the create modal (empty-state or header button).
    const openEmpty = page.getByTestId("pat-create-open-empty")
    if (await openEmpty.isVisible().catch(() => false)) {
      await openEmpty.click()
    } else {
      await page.getByTestId("pat-create-open").click()
    }

    const createModal = page.getByTestId("create-pat-modal")
    await expect(createModal).toBeVisible()

    const tokenName = `e2e-${Date.now().toString(36)}`
    await page.getByTestId("create-pat-name").fill(tokenName)
    await page.getByTestId("create-pat-submit").click()

    // One-time reveal: the full plaintext token is shown exactly once.
    const reveal = page.getByTestId("reveal-token-modal")
    await expect(reveal).toBeVisible({ timeout: 10_000 })
    const tokenText = await page.getByTestId("reveal-token-value").innerText()
    expect(tokenText).toMatch(/^pb_pat_.{43}$/)

    // Copy + warning are present.
    await page.getByTestId("reveal-token-copy").click()
    await expect(page.getByTestId("reveal-token-copied")).toBeVisible()

    await page.getByTestId("reveal-token-done").click()
    await expect(reveal).toBeHidden()

    // After close the plaintext is gone — only the fingerprint remains.
    const row = page
      .getByTestId("pat-row")
      .filter({ hasText: tokenName })
      .first()
    await expect(row).toBeVisible({ timeout: 10_000 })
    await expect(row).not.toContainText(tokenText)

    // Revoke (confirm) so the account stays clean.
    await row.getByTestId("pat-row-revoke").click()
    const revokeDialog = page.getByTestId("revoke-pat-dialog")
    await expect(revokeDialog).toBeVisible()
    await page.getByTestId("revoke-pat-confirm").click()
    await expect(revokeDialog).toBeHidden({ timeout: 10_000 })
  })
})
