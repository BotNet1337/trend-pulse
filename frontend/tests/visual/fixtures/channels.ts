import type { Page } from "@playwright/test"

export interface MockLinkedInOrganization {
  urn: string
  name: string
  logoUrl?: string | null
  vanityName?: string | null
}

export interface MockChannel {
  id: string
  workspaceId: string
  userId: string
  platform: "instagram" | "facebook" | "youtube" | "linkedin"
  name: string
  subject: string
  status: "active" | "expired" | "revoked" | "error"
  state: "active" | "deleted"
  meta: Record<string, unknown>
  organizations?: MockLinkedInOrganization[]
  connectedAt: string
  expiresAt: string | null
  createdAt: string
  updatedAt: string
}

const baseChannel = (
  overrides: Partial<MockChannel> & Pick<MockChannel, "workspaceId">,
): MockChannel => ({
  id: "11111111-1111-4111-8111-111111111111",
  userId: "33333333-3333-4333-8333-333333333333",
  platform: "instagram",
  name: "@example",
  subject: "ig:1",
  status: "active",
  state: "active",
  meta: {},
  connectedAt: new Date("2026-01-01T00:00:00Z").toISOString(),
  expiresAt: null,
  createdAt: new Date("2026-01-01T00:00:00Z").toISOString(),
  updatedAt: new Date("2026-01-01T00:00:00Z").toISOString(),
  ...overrides,
})

export const channelFactory = baseChannel

/**
 * Pre-installs a fake `window.open` so the OAuth popup never actually opens
 * in tests. The captured calls are exposed via `__oauthPopupCalls` on the
 * window so tests can assert on them.
 *
 * Important: addInitScript runs before any user code, so the override is in
 * place before `useInitiateOAuth` resolves.
 */
export const mockOAuthPopup = async (page: Page): Promise<void> => {
  await page.addInitScript(() => {
    type Call = { url: string; target: string; features: string }
    const calls: Call[] = []
    ;(window as unknown as { __oauthPopupCalls: Call[] }).__oauthPopupCalls = calls

    const realOpen = window.open.bind(window)
    window.open = ((
      url?: string | URL,
      target?: string,
      features?: string,
    ): Window | null => {
      const stringified = typeof url === "string" ? url : (url?.toString() ?? "")
      if (stringified.includes("/oauth/")) {
        calls.push({ url: stringified, target: target ?? "", features: features ?? "" })
        return {
          closed: false,
          focus() {},
          close() {},
          postMessage() {},
          location: { href: stringified },
        } as unknown as Window
      }
      return realOpen(url as string, target, features)
    }) as typeof window.open
  })
}

/**
 * Mocks the channels list endpoint with a fixed payload. Returns a function
 * that lets the test swap the response (e.g. simulate a list refetch after
 * a real-time event).
 */
export const mockChannelsList = async (
  page: Page,
  workspaceId: string,
  initial: MockChannel[],
): Promise<{ setChannels: (next: MockChannel[]) => void }> => {
  let current = initial

  await page.route(
    `**/api/workspaces/${workspaceId}/channels?**`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: current,
          meta: { total: current.length, offset: 0, limit: 100 },
        }),
      })
    },
  )

  return {
    setChannels: (next) => {
      current = next
    },
  }
}

export interface MockWorkspaceImage {
  id: string
  url: string
  mimeType: string
  meta: Record<string, unknown>
}

export interface MockWorkspaceOverrides {
  image?: MockWorkspaceImage | null
  postsCount?: number
  channelsCount?: number
}

export interface MockWorkspaceHandle {
  setOverrides: (next: MockWorkspaceOverrides) => void
}

export const mockWorkspace = async (
  page: Page,
  workspaceId: string,
  overrides: MockWorkspaceOverrides = {},
): Promise<MockWorkspaceHandle> => {
  let current: MockWorkspaceOverrides = {
    image: overrides.image ?? null,
    postsCount: overrides.postsCount ?? 0,
    channelsCount: overrides.channelsCount ?? 0,
  }
  await page.route(`**/api/workspaces/${workspaceId}`, async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: workspaceId,
        name: "QA Workspace",
        description: null,
        archivedAt: null,
        ownerId: "33333333-3333-4333-8333-333333333333",
        image: current.image ?? null,
        postsCount: current.postsCount ?? 0,
        channelsCount: current.channelsCount ?? 0,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }),
    })
  })

  return {
    setOverrides: (next) => {
      current = { ...current, ...next }
    },
  }
}

/**
 * Stubs the OAuth initiate endpoint so the dialog can complete without
 * touching the real provider. The returned URL is what `mockOAuthPopup`
 * captures.
 */
export const mockOAuthInitiate = async (
  page: Page,
  workspaceId: string,
  url = `https://provider.invalid/oauth/instagram?state=test`,
): Promise<void> => {
  await page.route(
    `**/api/workspaces/${workspaceId}/channels/oauth/*/initiate`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ url }),
      })
    },
  )
}

