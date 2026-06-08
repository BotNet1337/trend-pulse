import { test, expect } from "@playwright/test"

import { requireTestCredentials } from "./fixtures/auth"

const skipUnlessSignedIn = () => {
  const creds = requireTestCredentials()
  test.skip(
    !creds,
    "TEST_EMAIL / TEST_PASSWORD not set — skipping flow specs.",
  )
}

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

const seedWorkspace = async (
  request: import("@playwright/test").APIRequestContext,
  name: string,
): Promise<{ id: string }> => {
  const response = await request.post("/api/workspaces", {
    data: { name, description: null },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const json = (await response.json()) as { id: string }
  return { id: json.id }
}

test.describe("workspace · archive toggle", () => {
  test("Show archived swaps the visible set, Show active swaps it back", async ({
    page,
    request,
  }) => {
    skipUnlessSignedIn()

    const uniqueTag = `qa-archive-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const seed = await seedWorkspace(request, uniqueTag)

    try {
      const archiveResponse = await request.post(
        `/api/workspaces/${seed.id}/archive`,
      )
      expect(archiveResponse.ok(), await archiveResponse.text()).toBeTruthy()

      await page.goto("/workspaces")
      const toggle = page.locator('[data-testid="archive-toggle"]')
      await toggle.waitFor({ state: "visible", timeout: 10_000 })

      const cards = page.locator('[data-testid="workspace-card"]')
      const seedCard = cards.filter({ hasText: uniqueTag })

      // While "Show archived" is OFF, the seeded archived workspace must NOT show.
      await expect(seedCard).toHaveCount(0)

      // Toggle on → seeded archived workspace appears.
      await toggle.click()
      await expect(toggle).toHaveText(/Show active/i)
      await expect(seedCard).toHaveCount(1, { timeout: 5_000 })

      // Toggle off → archived disappears again, create card returns.
      await toggle.click()
      await expect(toggle).toHaveText(/Show archived/i)
      await expect(seedCard).toHaveCount(0)
      await expect(
        page.locator('[data-testid="create-workspace-card"]'),
      ).toBeVisible()
    } finally {
      // Hard-delete the seed workspace so the test is idempotent even on fail.
      await request.delete(`/api/workspaces/${seed.id}`)
    }
  })
})

test.describe("workspace · cover upload polling", () => {
  test("storage-object lookup retries on 404 until the row appears", async ({
    page,
  }) => {
    skipUnlessSignedIn()

    let lookupHits = 0
    // Always return 404 the first 2 times, then a synthetic StorageObject.
    await page.route(
      (url) => /\/api\/users\/[^/]+\/storage\/objects\/keys\//.test(url.toString()),
      async (route) => {
        lookupHits += 1
        if (lookupHits < 3) {
          await route.fulfill({
            status: 404,
            contentType: "application/json",
            body: JSON.stringify({
              statusCode: 404,
              code: 30001,
              message: "Storage object not found",
            }),
          })
          return
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "11111111-1111-4111-8111-111111111111",
            userId: "22222222-2222-4222-8222-222222222222",
            key: "test/key.png",
            size: 1024,
            mimeType: "image/png",
            checksum: null,
            metadata: {},
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          }),
        })
      },
    )

    // Stub presign + S3 PUT so we don't need a real bucket.
    await page.route("**/api/uploads/presign", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          urls: [
            {
              url: "https://example.invalid/upload/test-key",
              key: "test/key.png",
              mimeType: "image/png",
              metadata: {},
              expiresAt: new Date(Date.now() + 60_000).toISOString(),
            },
          ],
        }),
      })
    })
    await page.route("https://example.invalid/upload/**", async (route) => {
      await route.fulfill({ status: 200, body: "" })
    })

    await page.goto("/workspaces")
    await page
      .locator('[data-testid="create-workspace-card"]')
      .waitFor({ state: "visible", timeout: 10_000 })
    await page.locator('[data-testid="create-workspace-card"]').click()
    const dialog = page.locator('[data-testid="create-workspace-dialog"]')
    await dialog.waitFor({ state: "visible" })

    await dialog.locator('input[type="file"]').setInputFiles({
      name: "cover.png",
      mimeType: "image/png",
      buffer: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==",
        "base64",
      ),
    })

    // Wait for the polling loop to settle: photo tile shows the green
    // "selected" check once useUploadImage returns its result.
    await expect(async () => {
      expect(lookupHits, "lookup must have retried at least 3 times").toBeGreaterThanOrEqual(3)
    }).toPass({ timeout: 30_000 })

    expect(lookupHits).toBeGreaterThanOrEqual(3)
  })
})

test.describe("workspace · cover upload presign", () => {
  test("presign body carries a real UUID in metadata.userId", async ({
    page,
  }) => {
    skipUnlessSignedIn()

    await page.goto("/workspaces")
    await page
      .locator('[data-testid="create-workspace-card"]')
      .waitFor({ state: "visible", timeout: 10_000 })
    await page.locator('[data-testid="create-workspace-card"]').click()

    const dialog = page.locator('[data-testid="create-workspace-dialog"]')
    await dialog.waitFor({ state: "visible" })

    const presignPromise = page.waitForRequest(
      (req) =>
        req.url().endsWith("/api/uploads/presign") && req.method() === "POST",
      { timeout: 10_000 },
    )

    const fileInput = dialog.locator('input[type="file"]')
    await fileInput.setInputFiles({
      name: "cover.png",
      mimeType: "image/png",
      // 1×1 transparent PNG
      buffer: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==",
        "base64",
      ),
    })

    const presignReq = await presignPromise
    const body = JSON.parse(presignReq.postData() ?? "{}") as {
      metadata?: { userId?: string }
      files?: { mimeType?: string; size?: number }[]
    }

    expect(body.metadata?.userId, "userId must be a real UUID").toMatch(UUID_RE)
    expect(body.files?.[0]?.mimeType).toBe("image/png")
  })
})
