import axios, { type AxiosInstance } from 'axios';

const baseURL = process.env.API_URL;

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
