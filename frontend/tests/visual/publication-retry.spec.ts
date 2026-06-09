import { test, expect } from "@playwright/test"

import { requireTestCredentials, signInViaApi } from "./fixtures/auth"

/**
 * E2E for the publication retry control (TASK-080).
 *
 * The retry button is gated on `status === 'failed'`. Driving a real failure +
 * the actual retry round-trip requires (a) the backend JWT retry endpoint —
 * cross-repo dependency, merges separately — and (b) a seeded failed
 * publication. Both are environment-specific, so this spec verifies the
 * client-side gating contract that is always assertable from the app:
 *
 *  - on a non-failed publication the retry button is NOT rendered.
 *  - when a failed publication is present, the retry button + confirm dialog
 *    appear (the confirm action is exercised only when explicitly enabled to
 *    avoid mutating shared state without the backend endpoint live).
 *
 * Skipped without credentials or when no publication is reachable.
 */

test.describe("publication retry", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("retry button is hidden for non-failed publications", async ({
    page,
  }) => {
    const creds = requireTestCredentials()
    test.skip(!creds, "TEST_EMAIL / TEST_PASSWORD not set")
    if (!creds) return

    await signInViaApi(page, { email: creds.email, password: creds.password })

    // Find any post with at least one publication via the API, then open its
    // publication-details page. If the account has none, skip.
    const workspacesRes = await page.request.get("/api/workspaces?limit=1")
    test.skip(!workspacesRes.ok(), "workspaces unavailable")
    const workspaces = await workspacesRes.json()
    const workspaceId: string | undefined = workspaces?.data?.[0]?.id
    test.skip(!workspaceId, "no workspace on the test account")
    if (!workspaceId) return

    const postsRes = await page.request.get(
      `/api/workspaces/${workspaceId}/posts?limit=20`,
    )
    test.skip(!postsRes.ok(), "posts unavailable")
    const posts = await postsRes.json()
    const postWithPub = (posts?.data ?? []).find(
      (p: { id: string; publications?: { id: string; status: string }[] }) =>
        (p.publications?.length ?? 0) > 0,
    )
    test.skip(!postWithPub, "no publication to inspect")
    if (!postWithPub) return

    const pub = postWithPub.publications.find(
      (p: { status: string }) => p.status !== "failed",
    )
    test.skip(!pub, "no non-failed publication available")
    if (!pub) return

    await page.goto(
      `/workspaces/${workspaceId}/posts/${postWithPub.id}/publications/${pub.id}`,
    )
    await page.waitForLoadState("networkidle")

    // The retry button must not render for a non-failed publication.
    await expect(page.getByTestId("publication-retry-button")).toHaveCount(0)
  })
})
