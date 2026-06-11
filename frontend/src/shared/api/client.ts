import axios, { type AxiosError } from 'axios';

interface ZodIssue {
  path?: Array<string | number>;
  message?: string;
}

/** Unified error envelope shape (TASK-030). */
interface ErrorEnvelopeBody {
  /** TASK-030 unified envelope: {error: {code, message, details?}} */
  error?: { code?: string; message?: string };
  /** Legacy field (pre-TASK-030 or proxy response): {detail: str} */
  detail?: string | ZodIssue[];
  /** Zod/other message field kept for SSR/external services. */
  message?: string | ZodIssue[];
}

const GENERIC_ERROR_MESSAGE = 'Something went wrong. Please try again.';

/** Return the backend-provided message, or a generic fallback when absent. */
const resolveErrorMessage = (fallback?: string): string => fallback ?? GENERIC_ERROR_MESSAGE;

const friendlyFieldName = (path: Array<string | number> | undefined): string => {
  if (!path || path.length === 0) return 'Field';
  const last = String(path[path.length - 1]);
  return last
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/^./, (c) => c.toUpperCase());
};

const formatZodIssues = (issues: ZodIssue[]): string => {
  const seen = new Set<string>();
  const parts: string[] = [];
  for (const issue of issues) {
    const field = friendlyFieldName(issue.path);
    const note = issue.message && issue.message.toLowerCase() !== 'required'
      ? `${field}: ${issue.message}`
      : `${field} is required`;
    if (!seen.has(note)) {
      seen.add(note);
      parts.push(note);
    }
  }
  return parts.join('. ');
};

/**
 * Extract a human-readable message from the response body.
 * Checks (in priority order):
 *  1. Envelope error.message (TASK-030 unified format)
 *  2. Legacy detail string
 *  3. Zod/other message field
 */
const extractMessage = (data: ErrorEnvelopeBody | undefined): string | undefined => {
  if (!data) return undefined;
  // 1. Unified envelope (TASK-030)
  if (typeof data.error?.message === 'string' && data.error.message) return data.error.message;
  // 2. Legacy detail string
  if (typeof data.detail === 'string') return data.detail;
  // 3. Zod issues or other message field
  if (Array.isArray(data.message)) {
    return formatZodIssues(data.message);
  }
  return data.message;
};

// TrendPulse API client — cookie-auth (httpOnly, set by backend fastapi-users).
// baseURL: '/api/v1' — nginx strips /api/ and backend mounts all routes under /v1
// (TASK-030 / ADR-007: versioned API). The client appends relative paths such as
// '/auth/register' → full URL '/api/v1/auth/register' → backend /v1/auth/register.
// withCredentials: true → browser sends the fastapiusersauth cookie.
// No Bearer tokens, no localStorage. No refresh endpoint (TrendPulse uses
// session cookies; on 401 the user is redirected to /auth/sign-in).
export const apiClient = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
});

/**
 * Tag a request so the 401-redirect interceptor skips it.
 * Used for GET /users/me: auth state is managed by AuthGuard (react-query),
 * which handles the redirect itself. Without this flag, both the interceptor
 * AND the guard would race to redirect on the same 401.
 */
export const SKIP_REDIRECT_ON_401 = '__skipRedirectOn401';

const LOGOUT_PATH = '/auth/jwt/logout';
const SIGN_IN_PATH = '/auth/sign-in';

export const isSafeRedirect = (raw: string): boolean => {
  if (typeof raw !== 'string' || raw.length === 0) return false;
  if (!raw.startsWith('/')) return false;
  if (raw.startsWith('//')) return false;
  return true;
};

if (import.meta.env?.DEV && typeof window !== 'undefined') {
  (window as unknown as { __DEV_API_CLIENT__?: typeof apiClient }).__DEV_API_CLIENT__ = apiClient;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const data = error.response?.data as ErrorEnvelopeBody | undefined;
    error.message = resolveErrorMessage(extractMessage(data));

    const status = error.response?.status;
    const url = error.config?.url ?? '';
    const skipRedirect = !!(error.config as Record<string, unknown> | undefined)?.[SKIP_REDIRECT_ON_401];

    // On 401: redirect to sign-in.
    // Skip when:
    //  - the request itself is the logout endpoint (avoid redirect loop)
    //  - the request is tagged SKIP_REDIRECT_ON_401 (e.g. GET /users/me,
    //    which is polled by AuthGuard; the guard owns the redirect for that path)
    //  - already on an auth page
    if (
      status === 401 &&
      !skipRedirect &&
      !url.includes(LOGOUT_PATH) &&
      typeof window !== 'undefined'
    ) {
      const here = window.location.pathname + window.location.search;
      const onAuth = window.location.pathname.startsWith('/auth/');
      if (!onAuth) {
        const safeHere = isSafeRedirect(here) ? here : '/';
        window.location.assign(`${SIGN_IN_PATH}?redirect=${encodeURIComponent(safeHere)}`);
      }
    }

    return Promise.reject(error);
  },
);
