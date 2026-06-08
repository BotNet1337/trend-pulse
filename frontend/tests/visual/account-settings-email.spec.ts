import { test, expect } from "@playwright/test"

import { requireTestCredentials, signInViaApi } from "./fixtures/auth"
import {
  extractFirstHttpUrl,
  purgeMailbox,
  waitForMail,
} from "./fixtures/mailpit"

/**
 * E2E for the change-email flow on the Account Settings page. Skipped when
 * TEST_EMAIL / TEST_PASSWORD are missing — the spec mutates the test account's
 * email and rotates it back at the end. CI must use a dedicated throwaway
 * account.
 */

test.describe("account settings · change email", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("user can change their email and re-authenticate with the new address", async ({
    page,
  }) => {
    const creds = requireTestCredentials()
    test.skip(!creds, "TEST_EMAIL / TEST_PASSWORD not set")
    if (!creds) return

    const stamp = Date.now().toString(36)
    const newEmail = `${creds.email.replace("@", `+ec${stamp}@`)}`

    await purgeMailbox(page.request)
    await signInViaApi(page, { email: creds.email, password: creds.password })

    await page.goto("/account/settings")
    await page.waitForLoadState("networkidle")

    const emailSection = page.getByTestId("account-settings-email")
    await expect(emailSection).toBeVisible({ timeout: 10_000 })

    await page.getByTestId("account-settings-email-change").click()
    const dialog = page.getByTestId("change-email-dialog")
    await expect(dialog).toBeVisible()

    await page.getByTestId("change-email-new-email").fill(newEmail)
    await page.getByTestId("change-email-current-password").fill(creds.password)
    await page.getByTestId("change-email-confirm").click()

    await expect(page.getByTestId("change-email-sent")).toBeVisible({ timeout: 10_000 })

    const message = await waitForMail(page.request, {
      to: newEmail,
      subjectIncludes: "Confirm your new email",
    })
    const confirmUrl = extractFirstHttpUrl(message.HTML)
    expect(confirmUrl).toBeTruthy()

    await page.goto(confirmUrl as string)

    // Confirm landing page redirects to /auth/sign-in after success.
    await page.waitForURL(/\/auth\/sign-in/, { timeout: 10_000 })

    // 1. New email lets us sign in.
    const okResponse = await page.request.post("/api/auth/email/sign-in", {
      data: { email: newEmail, password: creds.password, rememberMe: true },
    })
    expect(okResponse.ok()).toBeTruthy()

    // 2. Old email no longer authenticates.
    const failResponse = await page.request.post("/api/auth/email/sign-in", {
      data: { email: creds.email, password: creds.password, rememberMe: false },
    })
    expect(failResponse.status()).not.toBe(200)

    // 3. Notice email landed in the OLD inbox.
    const notice = await waitForMail(page.request, {
      to: creds.email,
      subjectIncludes: "email was changed",
    })
    expect(notice.HTML.toLowerCase()).toContain(newEmail.toLowerCase())

    // 4. Rotate the email back so subsequent specs / re-runs are stable.
    await purgeMailbox(page.request)
    const rotateRequest = await page.request.post("/api/auth/email/request-change", {
      data: { currentPassword: creds.password, newEmail: creds.email },
    })
    expect(rotateRequest.ok()).toBeTruthy()

    const rotateMail = await waitForMail(page.request, {
      to: creds.email,
      subjectIncludes: "Confirm your new email",
    })
    const rotateUrl = extractFirstHttpUrl(rotateMail.HTML)
    expect(rotateUrl).toBeTruthy()
    await page.goto(rotateUrl as string)
    await page.waitForURL(/\/auth\/sign-in/, { timeout: 10_000 })
  })
})
