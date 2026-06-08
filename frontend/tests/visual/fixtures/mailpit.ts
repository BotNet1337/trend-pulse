import type { APIRequestContext } from "@playwright/test"

/**
 * Thin client over the Mailpit HTTP API. Used by playwright auth specs to
 * read confirm-email and reset-password links out of the dev mailbox so the
 * tests can drive the full flow end-to-end.
 *
 * Defaults assume the local nginx route at `https://mail.postbridge.local`
 * (see `development/nginx/templates/postbridge.conf.template`); override
 * via `MAILPIT_URL` for CI.
 */
export const MAILPIT_BASE_URL =
  process.env.MAILPIT_URL ?? "https://mail.postbridge.local"

export interface MailpitMessageSummary {
  ID: string
  Subject: string
  To: { Name: string; Address: string }[]
}

export interface MailpitMessage {
  ID: string
  Subject: string
  HTML: string
  Text: string
}

const mailpitGet = async <T>(
  request: APIRequestContext,
  path: string,
): Promise<T> => {
  const response = await request.get(`${MAILPIT_BASE_URL}${path}`, {
    ignoreHTTPSErrors: true,
  })
  if (!response.ok()) {
    throw new Error(
      `Mailpit GET ${path} failed: ${response.status()} ${await response.text()}`,
    )
  }
  return (await response.json()) as T
}

/**
 * Polls Mailpit until a message addressed to `recipient` matching the given
 * subject filter appears, or `timeoutMs` elapses. Returns the latest matching
 * message body so callers can pull tokens / links out of the HTML.
 */
export const waitForMail = async (
  request: APIRequestContext,
  filters: { to: string; subjectIncludes?: string },
  options: { timeoutMs?: number; pollMs?: number } = {},
): Promise<MailpitMessage> => {
  const timeoutMs = options.timeoutMs ?? 15_000
  const pollMs = options.pollMs ?? 500
  const deadline = Date.now() + timeoutMs

  while (Date.now() < deadline) {
    const list = await mailpitGet<{ messages: MailpitMessageSummary[] }>(
      request,
      "/api/v1/messages?limit=50",
    )
    const recipientLower = filters.to.toLowerCase()
    const match = list.messages.find((m) => {
      const recipientHit = m.To.some(
        (addr) => addr.Address.toLowerCase() === recipientLower,
      )
      if (!recipientHit) return false
      if (!filters.subjectIncludes) return true
      return m.Subject.toLowerCase().includes(
        filters.subjectIncludes.toLowerCase(),
      )
    })
    if (match) {
      return mailpitGet<MailpitMessage>(request, `/api/v1/message/${match.ID}`)
    }
    await new Promise((resolve) => setTimeout(resolve, pollMs))
  }

  throw new Error(
    `Mailpit timed out waiting for mail to ${filters.to}` +
      (filters.subjectIncludes ? ` (subject ~ "${filters.subjectIncludes}")` : ""),
  )
}

/**
 * Pulls the first absolute https URL from the rendered HTML of a Mailpit
 * message — confirm / reset emails embed a single CTA link that this matches.
 */
export const extractFirstHttpUrl = (html: string): string | null => {
  const match = html.match(/https?:\/\/[^\s"'<>]+/u)
  return match ? match[0] : null
}

/**
 * Convenience nuke for a clean slate at the start of a spec.
 */
export const purgeMailbox = async (request: APIRequestContext): Promise<void> => {
  await request.delete(`${MAILPIT_BASE_URL}/api/v1/messages`, {
    ignoreHTTPSErrors: true,
  })
}
