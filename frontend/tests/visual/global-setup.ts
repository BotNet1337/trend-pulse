import path from "node:path"
import { fileURLToPath } from "node:url"
import { mkdirSync } from "node:fs"

import { request, type FullConfig } from "@playwright/test"

import { requireTestCredentials, signInViaApi } from "./fixtures/auth"

const HERE = path.dirname(fileURLToPath(import.meta.url))
export const STATE_DIR = path.resolve(HERE, ".auth")
export const STORAGE_STATE_PATH = path.join(STATE_DIR, "state.json")

export default async function globalSetup(config: FullConfig): Promise<void> {
  const creds = requireTestCredentials()
  if (!creds) return

  const baseURL = config.projects[0]?.use.baseURL
  if (!baseURL) return

  mkdirSync(STATE_DIR, { recursive: true })

  const ctx = await request.newContext({
    baseURL,
    ignoreHTTPSErrors: true,
  })
  await signInViaApi(ctx, creds)
  await ctx.storageState({ path: STORAGE_STATE_PATH })
  await ctx.dispose()
}
