import axios, { type AxiosInstance } from 'axios';

const baseURL = process.env.API_URL;

export const serverApiClient: AxiosInstance = axios.create({
  baseURL,
  withCredentials: true,
});

/**
 * Build an axios instance scoped to a single SSR request.
 *
 * The upstream API authenticates via `Authorization: Bearer <jwt>` only
 * (passport-jwt `ExtractJwt.fromAuthHeaderAsBearerToken`), so we lift the
 * `access_token` out of the inbound cookies and stamp it as a Bearer header.
 * Forwarding the raw `Cookie` header alone — as the previous implementation
 * did — got every server-side fetcher 401'd, which the prefetch runner then
 * treated as a "drop hydration" signal, leaving `__INITIAL_STATE__.queries`
 * empty on every SSR render.
 *
 * The `AbortSignal` is shared across all per-request fetchers so a single
 * timeout aborts every in-flight call cooperatively.
 */
export interface CreateServerApiClientArgs {
  /**
   * JWT pulled from `request.cookies.access_token`. When undefined the
   * upstream call lands unauthenticated and the prefetch runner wipes
   * hydration to `[]` — which is the correct behaviour for an SSR request
   * with a stale or missing cookie.
   */
  accessToken?: string;
  signal?: AbortSignal;
}

export function createServerApiClient(args: CreateServerApiClientArgs): AxiosInstance {
  const headers: Record<string, string> = {};
  if (args.accessToken) {
    headers.Authorization = `Bearer ${args.accessToken}`;
  }

  return axios.create({
    baseURL,
    headers,
    signal: args.signal,
    // We carry auth via the explicit Bearer header above; `withCredentials`
    // is irrelevant in Node.
    withCredentials: false,
    // Treat any 2xx as success; any other status throws and is caught by the
    // prefetch runner. 401 specifically becomes a "drop everything" signal.
    validateStatus: (status) => status >= 200 && status < 300,
  });
}
