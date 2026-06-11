import axios, { type AxiosInstance } from 'axios';

// Backend mounts ALL routes under the /v1 version prefix (TASK-030 / ADR-007).
// The browser client gets the prefix via `baseURL: '/api/v1'` (nginx strips
// /api/ → backend sees /v1/...), but SSR prefetch talks to the api service
// DIRECTLY (API_URL=http://api:8000, no nginx in between), so the /v1 prefix
// must be appended here. Without it GET /users/me and /watchlists 404 and the
// prefetch runner silently drops hydration → __INITIAL_STATE__.user is null
// even for authenticated requests (e2e ssr.spec.ts AC3).
//
// NOTE: API_URL itself must stay WITHOUT /v1 — server.factory.ts reuses it as
// the upstream for the /api and /socket.io proxies, where the version prefix
// arrives in the browser-supplied path.
export const versionedApiBaseUrl = (apiUrl: string | undefined): string | undefined =>
  apiUrl ? `${apiUrl.replace(/\/+$/, '')}/v1` : undefined;

const baseURL = versionedApiBaseUrl(process.env.API_URL);

/**
 * Build an axios instance scoped to a single SSR request.
 *
 * TrendPulse backend authenticates via **httpOnly cookie** (`fastapiusersauth`)
 * set by fastapi-users `CookieTransport`. Bearer tokens are NOT used — the API
 * has no `ExtractJwt.fromAuthHeaderAsBearerToken` path.
 *
 * In SSR we receive the inbound `Cookie` request header (containing
 * `fastapiusersauth`) and forward it verbatim to the upstream API via the
 * explicit `Cookie` header on the axios instance. Node's http(s) does not send
 * cookies automatically (`withCredentials` is a browser-only concept), so we
 * must set the header explicitly.
 *
 * The `AbortSignal` is shared across all per-request fetchers so a single
 * timeout aborts every in-flight call cooperatively.
 *
 * 401 from the upstream is NOT swallowed here — the prefetch runner catches it
 * via `Promise.allSettled` and treats it as a "drop hydration" signal, leaving
 * `__INITIAL_STATE__.queries` empty so the client refetches and AuthGuard
 * redirects to /auth/sign-in.
 */
export interface CreateServerApiClientArgs {
  /**
   * The raw `Cookie` request header from the inbound SSR request (e.g.
   * `req.headers.cookie`). When undefined the upstream call lands
   * unauthenticated — correct behaviour for an anonymous SSR request.
   */
  cookieHeader?: string;
  signal?: AbortSignal;
}

export function createServerApiClient(args: CreateServerApiClientArgs): AxiosInstance {
  const headers: Record<string, string> = {};
  if (args.cookieHeader) {
    headers['Cookie'] = args.cookieHeader;
  }

  return axios.create({
    baseURL,
    headers,
    signal: args.signal,
    // withCredentials is irrelevant in Node — we forward cookies explicitly
    // via the Cookie header above.
    withCredentials: false,
    // Treat any 2xx as success; any other status throws and is caught by the
    // prefetch runner. 401 specifically becomes a "drop everything" signal.
    validateStatus: (status) => status >= 200 && status < 300,
  });
}
