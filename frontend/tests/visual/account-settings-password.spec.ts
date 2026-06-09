import { test, expect } from "@playwright/test"

import { requireTestCredentials, signInViaApi } from "./fixtures/auth"

/**
 * E2E for the change-password flow on the Account Settings page. Skipped
 * when TEST_EMAIL / TEST_PASSWORD are missing — the spec mutates the test
 * account's password and rotates it back at the end. CI must use a
 * dedicated throwaway account.
 */

test.describe("account settings · change password", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("user can change their password and re-authenticate with it", async ({
    page,
  }) => {
    const creds = requireTestCredentials()
    test.skip(!creds, "TEST_EMAIL / TEST_PASSWORD not set")
    if (!creds) return

    const newPassword = `Pw!${Date.now().toString(36)}AaA`

    // 1. Programmatic sign-in seeds cookies for the UI flow.
    await signInViaApi(page, { email: creds.email, password: creds.password })

    await page.goto("/account/settings")
    await page.waitForLoadState("networkidle")

    const passwordSection = page.getByTestId("account-settings-password")
    await expect(passwordSection).toBeVisible({ timeout: 10_000 })

    await page.getByTestId("account-settings-password-change").click()
    const dialog = page.getByTestId("change-password-dialog")
    await expect(dialog).toBeVisible()

    await dialog.getByLabel("Current password").fill(creds.password)
    await dialog.getByLabel("New password").fill(newPassword)
    await dialog.getByLabel("Confirm new password").fill(newPassword)

    await page.getByTestId("change-password-confirm").click()
    await expect(dialog).toBeHidden({ timeout: 10_000 })

    // 2. Old password no longer works.
    const failResponse = await page.request.post("/api/auth/email/sign-in", {
      data: { email: creds.email, password: creds.password, rememberMe: false },
    })
    expect(failResponse.status()).toBe(401)

    // 3. New password works — verify, then rotate the password back so the
    //    account stays usable for subsequent specs / re-runs.
    const okResponse = await page.request.post("/api/auth/email/sign-in", {
      data: { email: creds.email, password: newPassword, rememberMe: true },
    })
    expect(okResponse.ok()).toBeTruthy()

    const rotateBack = await page.request.patch("/api/auth/password", {
      data: { currentPassword: newPassword, newPassword: creds.password },
    })
    expect(rotateBack.ok()).toBeTruthy()
  })
})
