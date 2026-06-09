import { test, expect } from "@playwright/test"

import { requireTestCredentials } from "./fixtures/auth"
import { mockWorkspace } from "./fixtures/channels"
import { mockPostsList } from "./fixtures/posts"
import {
  buildCalendarPost,
  mockReschedulePublication,
  performHtml5Drag,
} from "./fixtures/calendar"

const skipUnlessSignedIn = () => {
  const creds = requireTestCredentials()
  test.skip(
    !creds,
    "TEST_EMAIL / TEST_PASSWORD not set — skipping calendar flow specs.",
  )
}

const WORKSPACE_ID = "44444444-4444-4444-8444-444444444444"

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
] as const

const buildAt = (delta: { days: number; hour?: number; minute?: number }) => {
  const now = new Date()
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + delta.days, delta.hour ?? 12, delta.minute ?? 0, 0, 0)
  return next
}

const isoDateOf = (date: Date): string => {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, "0")
  const d = String(date.getDate()).padStart(2, "0")
  return `${y}-${m}-${d}`
}

const monthLabelOf = (date: Date): string =>
  `${MONTH_NAMES[date.getMonth()]} ${date.getFullYear()}`

test.describe("calendar · empty state", () => {
  test("empty workspace shows the quiet-week copy and a Schedule a post CTA", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)
    await mockPostsList(page, WORKSPACE_ID, [])

    await page.goto(`/workspaces/${WORKSPACE_ID}/calendar`)

    await expect(page.getByTestId("calendar-toolbar")).toBeVisible()
    await expect(
      page.getByRole("heading", { name: "A quiet week ahead" }),
    ).toBeVisible()
    await expect(page.getByTestId("calendar-empty-cta")).toBeEnabled()
    await expect(page.getByTestId("calendar-new-post")).toBeEnabled()
  })
})

test.describe("calendar · month grid", () => {
  test("renders 42 cells, today highlighted, navigation shifts the title", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)
    const todayAt = buildAt({ days: 0, hour: 14 })
    await mockPostsList(page, WORKSPACE_ID, [
      buildCalendarPost({
        workspaceId: WORKSPACE_ID,
        postId: "55555555-5555-4555-8555-555555555000",
        name: "Launch teaser",
        slots: [{ publishAt: todayAt.toISOString() }],
      }),
    ])

    await page.goto(`/workspaces/${WORKSPACE_ID}/calendar`)

    await expect(page.getByTestId("calendar-grid")).toBeVisible()
    const cells = page.locator('[data-testid^="calendar-cell-"]')
    await expect(cells).toHaveCount(42)

    const todayIso = isoDateOf(new Date())
    await expect(page.getByTestId(`calendar-cell-${todayIso}`)).toBeVisible()

    const initialTitle = monthLabelOf(new Date())
    await expect(page.getByTestId("calendar-title")).toHaveText(initialTitle)

    await page.getByTestId("calendar-prev").click()
    await expect(page.getByTestId("calendar-title")).not.toHaveText(initialTitle)

    await page.getByTestId("calendar-today").click()
    await expect(page.getByTestId("calendar-title")).toHaveText(initialTitle)
  })
})

test.describe("calendar · day-details modal", () => {
  test("clicking a day with events opens the modal and filter narrows the list", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)
    const targetAt = buildAt({ days: 1, hour: 12 })
    const post = buildCalendarPost({
      workspaceId: WORKSPACE_ID,
      postId: "55555555-5555-4555-8555-555555555100",
      name: "Office tour",
      slots: [
        {
          publishAt: targetAt.toISOString(),
          status: "published",
          publishedAt: targetAt.toISOString(),
          publicationId: "66666666-6666-4666-8666-666666660001",
        },
        {
          publishAt: new Date(targetAt.getTime() + 60 * 60 * 1000).toISOString(),
          status: "pending",
          publicationId: "66666666-6666-4666-8666-666666660002",
        },
      ],
    })
    await mockPostsList(page, WORKSPACE_ID, [post])

    await page.goto(`/workspaces/${WORKSPACE_ID}/calendar`)

    const targetIso = isoDateOf(targetAt)
    await page.getByTestId(`calendar-cell-${targetIso}`).click()

    await expect(page.getByTestId("calendar-day-modal")).toBeVisible()
    await expect(
      page.getByTestId("calendar-day-item-66666666-6666-4666-8666-666666660001"),
    ).toBeVisible()
    await expect(
      page.getByTestId("calendar-day-item-66666666-6666-4666-8666-666666660002"),
    ).toBeVisible()

    await page.getByTestId("calendar-day-filter-published").click()
    await expect(
      page.getByTestId("calendar-day-item-66666666-6666-4666-8666-666666660001"),
    ).toBeVisible()
    await expect(
      page.getByTestId("calendar-day-item-66666666-6666-4666-8666-666666660002"),
    ).toHaveCount(0)
  })
})

test.describe("calendar · drag to reschedule", () => {
  test("drag from one day to another sends PATCH with new publishAt", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)
    const sourceAt = buildAt({ days: 2, hour: 9 })
    const targetAt = buildAt({ days: 4 })
    const PUBLICATION_ID = "66666666-6666-4666-8666-666666660777"
    const post = buildCalendarPost({
      workspaceId: WORKSPACE_ID,
      postId: "55555555-5555-4555-8555-555555555200",
      name: "Drag candidate",
      slots: [
        {
          publishAt: sourceAt.toISOString(),
          status: "pending",
          publicationId: PUBLICATION_ID,
        },
      ],
    })
    await mockPostsList(page, WORKSPACE_ID, [post])
    const reschedule = await mockReschedulePublication(page, WORKSPACE_ID)

    await page.goto(`/workspaces/${WORKSPACE_ID}/calendar`)

    const sourceCell = page.getByTestId(`calendar-cell-${isoDateOf(sourceAt)}`)
    const targetCell = page.getByTestId(`calendar-cell-${isoDateOf(targetAt)}`)
    const eventChip = page.getByTestId(`calendar-event-${PUBLICATION_ID}`)

    await expect(sourceCell).toBeVisible()
    await expect(targetCell).toBeVisible()
    await expect(eventChip).toBeVisible()

    await performHtml5Drag(page, eventChip, targetCell)

    await expect.poll(() => reschedule.calls().length).toBeGreaterThan(0)
    const call = reschedule.calls()[0]
    expect(call.publicationId).toBe(PUBLICATION_ID)
    const sentDate = new Date(call.body.publishAt)
    expect(isoDateOf(sentDate)).toBe(isoDateOf(targetAt))
  })
})

test.describe("calendar · streak", () => {
  test("3+ consecutive published days surface the streak pill", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)
    const slots = [0, 1, 2].map((delta) => {
      const at = buildAt({ days: -delta })
      return {
        publishAt: at.toISOString(),
        status: "published" as const,
        publishedAt: at.toISOString(),
        publicationId: `66666666-6666-4666-8666-66666666${String(delta).padStart(4, "0")}`,
      }
    })
    const post = buildCalendarPost({
      workspaceId: WORKSPACE_ID,
      postId: "55555555-5555-4555-8555-555555555300",
      name: "Streak owner",
      status: "published",
      slots,
    })
    await mockPostsList(page, WORKSPACE_ID, [post])

    await page.goto(`/workspaces/${WORKSPACE_ID}/calendar`)
    await expect(page.getByTestId("calendar-streak")).toBeVisible()
    await expect(page.getByTestId("calendar-streak")).toContainText("3")
  })
})
