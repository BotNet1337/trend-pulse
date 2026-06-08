/**
 * Generic polling utility. Calls `fn` repeatedly until it either resolves
 * with a value (success) or `timeoutMs` elapses (failure). Between failed
 * attempts it waits with exponential backoff capped at `maxDelayMs`.
 *
 * `fn` can signal "not yet, try again" in one of two ways:
 *   1. throw an error and `shouldRetry(error)` returns true; OR
 *   2. resolve with `undefined` (handy for "lookup returns null when missing").
 *
 * Any error for which `shouldRetry` returns false is surfaced immediately.
 */

export interface PollOptions {
  /** Total time the loop is allowed to run before giving up. Default: 60s. */
  timeoutMs?: number
  /** Delay before the second attempt. Default: 500ms. */
  initialDelayMs?: number
  /** Cap for the backoff so we don't sleep forever. Default: 2.5s. */
  maxDelayMs?: number
  /** Multiplier applied to the previous delay each iteration. Default: 1.5. */
  factor?: number
  /** External cancellation. Throws on abort. */
  signal?: AbortSignal
  /**
   * Decides whether a thrown error should trigger another attempt or be
   * surfaced verbatim. Default: every error is retryable.
   */
  shouldRetry?: (error: unknown) => boolean
  /**
   * Custom message thrown when the loop times out. Receives the last error
   * (if any) so callers can include it for debugging.
   */
  onTimeout?: (lastError: unknown) => Error
}

const DEFAULTS = {
  timeoutMs: 60_000,
  initialDelayMs: 500,
  maxDelayMs: 2_500,
  factor: 1.5,
} as const

const sleep = (ms: number, signal?: AbortSignal): Promise<void> =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new Error("aborted"))
      return
    }
    const id = setTimeout(resolve, ms)
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(id)
        reject(signal.reason ?? new Error("aborted"))
      },
      { once: true },
    )
  })

export async function poll<T>(
  fn: () => Promise<T | undefined>,
  options: PollOptions = {},
): Promise<T> {
  const timeoutMs = options.timeoutMs ?? DEFAULTS.timeoutMs
  const maxDelayMs = options.maxDelayMs ?? DEFAULTS.maxDelayMs
  const factor = options.factor ?? DEFAULTS.factor
  const shouldRetry = options.shouldRetry ?? (() => true)

  const deadline = Date.now() + timeoutMs
  let delay: number = options.initialDelayMs ?? DEFAULTS.initialDelayMs
  let lastError: unknown

  while (Date.now() < deadline) {
    options.signal?.throwIfAborted()
    try {
      const value = await fn()
      if (value !== undefined) return value
      // `undefined` resolution means "not yet" — fall through to backoff.
    } catch (error) {
      if (!shouldRetry(error)) throw error
      lastError = error
    }

    const remaining = deadline - Date.now()
    if (remaining <= 0) break
    await sleep(Math.min(delay, remaining), options.signal)
    delay = Math.min(Math.round(delay * factor), maxDelayMs)
  }

  if (options.onTimeout) throw options.onTimeout(lastError)
  throw new Error(
    `poll: timed out after ${Math.round(timeoutMs / 1000)}s${
      lastError instanceof Error ? ` (last error: ${lastError.message})` : ""
    }`,
  )
}
