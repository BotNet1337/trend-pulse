import { test, expect } from "@playwright/test"

import { requireTestCredentials } from "./fixtures/auth"
import {
  channelFactory,
  mockChannelsList,
  mockWorkspace,
} from "./fixtures/channels"
import {
  mockPostsCreate,
  mockPostsList,
  mockPostFindById,
  mockPostDelete,
  mockPostUpdate,
  mockPublicationsCreate,
  postFactory,
  publicationFactory,
  type MockPostAggregate,
} from "./fixtures/posts"

const skipUnlessSignedIn = () => {
  const creds = requireTestCredentials()
  test.skip(
    !creds,
    "TEST_EMAIL / TEST_PASSWORD not set — skipping posts flow specs.",
  )
}

const WORKSPACE_ID = "44444444-4444-4444-8444-444444444444"
const POST_ID = "55555555-5555-4555-8555-555555555555"

test.describe("posts · empty state", () => {
  test("empty workspace shows the templates copy and a New post CTA", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)
    await mockPostsList(page, WORKSPACE_ID, [])

    await page.goto(`/workspaces/${WORKSPACE_ID}/posts`)
    await expect(page.getByRole("heading", { name: "Posts" })).toBeVisible()
    await expect(
      page.getByRole("heading", { name: "Your posts will land here" }),
    ).toBeVisible()
    await expect(page.getByTestId("posts-new-post")).toBeEnabled()
  })
})

test.describe("posts · create", () => {
  test("opening the dialog, filling the form and submitting routes to post details", async ({
    page,
  }) => {
    skipUnlessSignedIn()

    await mockWorkspace(page, WORKSPACE_ID)
    const list = await mockPostsList(page, WORKSPACE_ID, [])
    const created = postFactory({
      workspaceId: WORKSPACE_ID,
      id: POST_ID,
      name: "Launch deck",
      description: "Tease the launch",
      tags: ["launch", "team-culture"],
    })
    const create = await mockPostsCreate(page, WORKSPACE_ID, created)
    await mockPostFindById(page, WORKSPACE_ID, POST_ID, () => created)
    await mockChannelsList(page, WORKSPACE_ID, [])

    await page.goto(`/workspaces/${WORKSPACE_ID}/posts`)

    await page.getByTestId("posts-new-post").click()
    const dialog = page.getByTestId("create-post-dialog")
    await expect(dialog).toBeVisible()

    await dialog.locator("#post-create-name").fill("Launch deck")
    await dialog.locator("#post-create-description").fill("Tease the launch")
    const tagInput = dialog.getByLabel("Add tag")
    await tagInput.fill("launch")
    await tagInput.press("Enter")
    await tagInput.fill("team-culture")
    await tagInput.press("Enter")

    list.setPosts([created])

    await dialog
      .getByRole("button", { name: "Create post → set up publications" })
      .click()

    await expect(page).toHaveURL(
      new RegExp(`/workspaces/${WORKSPACE_ID}/posts/${POST_ID}$`),
    )
    expect(create.lastPayload()).toMatchObject({
      name: "Launch deck",
      description: "Tease the launch",
      tags: ["launch", "team-culture"],
    })
  })
})

test.describe("posts · list filter tabs", () => {
  test("status tabs filter the visible cards via API params", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)
    const queryRef: { current: URLSearchParams | null } = { current: null }
    const data: MockPostAggregate[] = [
      postFactory({
        workspaceId: WORKSPACE_ID,
        id: "post-draft",
        name: "Draft post",
        status: "draft",
      }),
      postFactory({
        workspaceId: WORKSPACE_ID,
        id: "post-publishing",
        name: "In flight",
        status: "publishing",
      }),
    ]

    await page.route(
      `**/api/workspaces/${WORKSPACE_ID}/posts?**`,
      async (route) => {
        const url = new URL(route.request().url())
        queryRef.current = url.searchParams
        const status = url.searchParams.get("status")
        const filtered = status
          ? data.filter((post) => post.status === status)
          : data
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: filtered,
            meta: { total: filtered.length, offset: 0, limit: 60 },
          }),
        })
      },
    )

    await page.goto(`/workspaces/${WORKSPACE_ID}/posts`)
    await expect(page.locator('[data-testid="post-card"]')).toHaveCount(2)

    await page.getByRole("tab", { name: /Draft/ }).click()
    await expect(page.locator('[data-testid="post-card"]')).toHaveCount(1)
    expect(queryRef.current?.get("status")).toBe("draft")

    await page.getByRole("tab", { name: /All/ }).click()
    await expect(page.locator('[data-testid="post-card"]')).toHaveCount(2)
    expect(queryRef.current?.get("status")).toBeNull()
  })
})

test.describe("posts · delete", () => {
  test("confirmation dialog deletes and routes back to the list", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)

    const post = postFactory({
      workspaceId: WORKSPACE_ID,
      id: POST_ID,
      name: "Boring update",
    })
    const list = await mockPostsList(page, WORKSPACE_ID, [post])
    await mockPostFindById(page, WORKSPACE_ID, POST_ID, () => post)
    const deleteHandle = await mockPostDelete(page, WORKSPACE_ID, POST_ID)
    await mockChannelsList(page, WORKSPACE_ID, [])

    await page.goto(`/workspaces/${WORKSPACE_ID}/posts/${POST_ID}`)
    await page.getByTestId("post-details-delete").click()

    list.setPosts([])

    const dialog = page.getByTestId("delete-post-dialog")
    await expect(dialog).toBeVisible()
    await dialog.getByRole("button", { name: "Delete post" }).click()

    await expect(page).toHaveURL(
      new RegExp(`/workspaces/${WORKSPACE_ID}/posts$`),
    )
    expect(deleteHandle.called()).toBeTruthy()
  })
})

test.describe("posts · edit", () => {
  test("opens, prefills, patches and shows the new caption", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)

    let post = postFactory({
      workspaceId: WORKSPACE_ID,
      id: POST_ID,
      name: "Initial name",
      description: "Initial caption.",
      tags: ["one"],
    })
    await mockPostsList(page, WORKSPACE_ID, [post])
    await mockPostFindById(page, WORKSPACE_ID, POST_ID, () => post)
    await mockChannelsList(page, WORKSPACE_ID, [])

    const updated = postFactory({
      ...post,
      name: "New name",
      description: "Better caption.",
      tags: ["one", "launch"],
    })
    const update = await mockPostUpdate(page, WORKSPACE_ID, POST_ID, updated)

    await page.goto(`/workspaces/${WORKSPACE_ID}/posts/${POST_ID}`)
    await page.getByTestId("post-details-edit").click()

    const dialog = page.getByTestId("edit-post-dialog")
    await expect(dialog).toBeVisible()
    await expect(dialog.locator("#post-edit-name")).toHaveValue("Initial name")
    await expect(dialog.locator("#post-edit-description")).toHaveValue(
      "Initial caption.",
    )

    await dialog.locator("#post-edit-name").fill("New name")
    await dialog.locator("#post-edit-description").fill("Better caption.")
    const tagInput = dialog.getByLabel("Add tag")
    await tagInput.fill("launch")
    await tagInput.press("Enter")

    // Server response after the patch — find-by-id should now reflect the
    // updated post via React Query setQueryData.
    post = updated
    await dialog.getByRole("button", { name: "Save changes" }).click()

    await expect(dialog).toBeHidden()
    expect(update.lastPayload()).toMatchObject({
      name: "New name",
      description: "Better caption.",
      tags: ["one", "launch"],
    })
    await expect(page.getByText("Better caption.")).toBeVisible()
  })
})

test.describe("posts · navigation between pages", () => {
  test("posts list → post-details → publication-details navigates and back", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)
    await mockChannelsList(page, WORKSPACE_ID, [])

    const publication = publicationFactory({
      workspaceId: WORKSPACE_ID,
      postId: POST_ID,
      id: "66666666-6666-4666-8666-666666666666",
      channelId: "11111111-1111-4111-8111-111111111111",
      postType: "instagram_feed",
      status: "published",
      publishedAt: "2026-04-01T12:00:00Z",
    })
    const post = postFactory({
      workspaceId: WORKSPACE_ID,
      id: POST_ID,
      name: "Linkable post",
      publications: [publication],
      counts: {
        total: 1,
        pending: 0,
        publishing: 0,
        published: 1,
        failed: 0,
      },
    })
    await mockPostsList(page, WORKSPACE_ID, [post])
    await mockPostFindById(page, WORKSPACE_ID, POST_ID, () => post)

    await page.goto(`/workspaces/${WORKSPACE_ID}/posts`)
    await expect(page.getByRole("heading", { name: "Posts" })).toBeVisible()
    await page.locator(`[data-post-id="${POST_ID}"]`).click()

    await expect(page).toHaveURL(
      new RegExp(`/workspaces/${WORKSPACE_ID}/posts/${POST_ID}$`),
    )
    await expect(page.getByRole("heading", { name: "Linkable post" })).toBeVisible()

    await page
      .locator(`[data-publication-id="${publication.id}"]`)
      .first()
      .click()
    await expect(page).toHaveURL(
      new RegExp(
        `/workspaces/${WORKSPACE_ID}/posts/${POST_ID}/publications/${publication.id}$`,
      ),
    )
    await expect(page.getByText(/posted to/i)).toBeVisible()

    await page.getByRole("button", { name: /Back to post/i }).click()
    await expect(page).toHaveURL(
      new RegExp(`/workspaces/${WORKSPACE_ID}/posts/${POST_ID}$`),
    )
  })

  test("publication-details with unknown id renders not-found state", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)
    await mockChannelsList(page, WORKSPACE_ID, [])

    const post = postFactory({
      workspaceId: WORKSPACE_ID,
      id: POST_ID,
      name: "No publications here",
    })
    await mockPostsList(page, WORKSPACE_ID, [post])
    await mockPostFindById(page, WORKSPACE_ID, POST_ID, () => post)

    await page.goto(
      `/workspaces/${WORKSPACE_ID}/posts/${POST_ID}/publications/77777777-7777-4777-8777-777777777777`,
    )
    await expect(page.getByText(/doesn't exist on the current post/)).toBeVisible()
  })
})

test.describe("publications · add publication flow", () => {
  test("walks through 3 steps and submits the channels payload", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)

    const channel = channelFactory({
      workspaceId: WORKSPACE_ID,
      id: "11111111-1111-4111-8111-111111111111",
      name: "@postbolt",
      subject: "ig:postbolt",
    })
    await mockChannelsList(page, WORKSPACE_ID, [channel])

    const post = postFactory({
      workspaceId: WORKSPACE_ID,
      id: POST_ID,
      name: "Carousel of joy",
    })
    await mockPostsList(page, WORKSPACE_ID, [post])
    await mockPostFindById(page, WORKSPACE_ID, POST_ID, () => post)

    const publishHandle = await mockPublicationsCreate(
      page,
      WORKSPACE_ID,
      POST_ID,
      () => [
        publicationFactory({
          workspaceId: WORKSPACE_ID,
          postId: POST_ID,
          channelId: channel.id,
          postType: "instagram_reels",
        }),
      ],
    )

    await page.goto(`/workspaces/${WORKSPACE_ID}/posts/${POST_ID}`)
    await page.getByTestId("post-details-add-publication").click()

    const dialog = page.getByTestId("add-publication-dialog")
    await expect(dialog).toBeVisible()
    await dialog.getByTestId(`add-publication-channel-${channel.id}`).click()
    await dialog.getByRole("button", { name: "Next: pick post type" }).click()

    await dialog.getByTestId("add-publication-post-type-instagram_reels").click()
    await dialog.getByRole("button", { name: "Next: configure" }).click()

    await dialog.getByRole("button", { name: "Add publication" }).click()

    await expect(dialog).toBeHidden()
    expect(publishHandle.lastPayload()).toMatchObject({
      channels: [
        {
          channelId: channel.id,
          postType: "instagram_reels",
        },
      ],
    })
  })

  test("a smart chip adds an optional field that reaches the POST body", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)

    const channel = channelFactory({
      workspaceId: WORKSPACE_ID,
      id: "11111111-1111-4111-8111-111111111111",
      name: "@postbolt",
      subject: "ig:postbolt",
    })
    await mockChannelsList(page, WORKSPACE_ID, [channel])

    const post = postFactory({
      workspaceId: WORKSPACE_ID,
      id: POST_ID,
      name: "Tagged carousel",
    })
    await mockPostsList(page, WORKSPACE_ID, [post])
    await mockPostFindById(page, WORKSPACE_ID, POST_ID, () => post)

    const publishHandle = await mockPublicationsCreate(
      page,
      WORKSPACE_ID,
      POST_ID,
      () => [
        publicationFactory({
          workspaceId: WORKSPACE_ID,
          postId: POST_ID,
          channelId: channel.id,
          postType: "instagram_feed",
        }),
      ],
    )

    await page.goto(`/workspaces/${WORKSPACE_ID}/posts/${POST_ID}`)
    await page.getByTestId("post-details-add-publication").click()

    const dialog = page.getByTestId("add-publication-dialog")
    await expect(dialog).toBeVisible()
    await dialog.getByTestId(`add-publication-channel-${channel.id}`).click()
    await dialog.getByRole("button", { name: "Next: pick post type" }).click()
    await dialog.getByTestId("add-publication-post-type-instagram_feed").click()
    await dialog.getByRole("button", { name: "Next: configure" }).click()

    await dialog.getByTestId("add-meta-chip-Location").click()
    await dialog.getByPlaceholder("Facebook Places id").fill("42")

    await dialog.getByRole("button", { name: "Add publication" }).click()

    await expect(dialog).toBeHidden()
    expect(publishHandle.lastPayload()).toMatchObject({
      channels: [
        {
          channelId: channel.id,
          postType: "instagram_feed",
          meta: { locationId: "42" },
        },
      ],
    })
  })

  test("the LinkedIn org-selector writes the chosen page urn into the POST body", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)

    const channel = channelFactory({
      workspaceId: WORKSPACE_ID,
      id: "22222222-2222-4222-8222-222222222222",
      platform: "linkedin",
      name: "Yarik",
      subject: "li:yarik",
      organizations: [
        { urn: "urn:li:organization:111", name: "Acme Inc" },
        { urn: "urn:li:organization:222", name: "Beta LLC" },
      ],
    })
    await mockChannelsList(page, WORKSPACE_ID, [channel])

    const post = postFactory({
      workspaceId: WORKSPACE_ID,
      id: POST_ID,
      name: "Company update",
    })
    await mockPostsList(page, WORKSPACE_ID, [post])
    await mockPostFindById(page, WORKSPACE_ID, POST_ID, () => post)

    const publishHandle = await mockPublicationsCreate(
      page,
      WORKSPACE_ID,
      POST_ID,
      () => [
        publicationFactory({
          workspaceId: WORKSPACE_ID,
          postId: POST_ID,
          channelId: channel.id,
          postType: "linkedin_organization",
        }),
      ],
    )

    await page.goto(`/workspaces/${WORKSPACE_ID}/posts/${POST_ID}`)
    await page.getByTestId("post-details-add-publication").click()

    const dialog = page.getByTestId("add-publication-dialog")
    await expect(dialog).toBeVisible()
    await dialog.getByTestId(`add-publication-channel-${channel.id}`).click()
    await dialog.getByRole("button", { name: "Next: pick post type" }).click()
    await dialog
      .getByTestId("add-publication-post-type-linkedin_organization")
      .click()
    await dialog.getByRole("button", { name: "Next: configure" }).click()

    await dialog.getByTestId("linkedin-org-urn:li:organization:222").click()
    await dialog.getByRole("button", { name: "Add publication" }).click()

    await expect(dialog).toBeHidden()
    expect(publishHandle.lastPayload()).toMatchObject({
      channels: [
        {
          channelId: channel.id,
          postType: "linkedin_organization",
          meta: { organizationUrn: "urn:li:organization:222" },
        },
      ],
    })
  })
})
