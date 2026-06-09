import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { resolveErrorMessage } from '@/shared/lib';

interface RetryableConfig extends InternalAxiosRequestConfig {
  _retry?: boolean;
}

interface ZodIssue {
  path?: Array<string | number>;
  message?: string;
}

interface ErrorBody {
  message?: string | ZodIssue[];
  code?: number;
}

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

const extractMessage = (data: ErrorBody | undefined): string | undefined => {
  if (!data) return undefined;
  if (Array.isArray(data.message)) {
    return formatZodIssues(data.message);
  }
  return data.message;
};

export const apiClient = axios.create({
  baseURL: '/api',
  withCredentials: true,
});

const REFRESH_PATH = '/auth/token/refresh';
const SIGN_OUT_PATH = '/auth/sign-out';
// Fastify-side refresh endpoint (see `apps/frontend/server/plugins/refresh.plugin.ts`).
// Lives outside the `/api` proxy so the refresh hop has its own URL surface
// — easier to scope cookies / add CSRF later, and keeps the browser away
// from any direct knowledge of refresh-token handling.
const SSR_REFRESH_PATH = '/__auth/refresh';

let refreshInFlight: Promise<void> | null = null;

// SECURITY (TASK-AUDIT-RELEASE-1 / H8):
// Bound the refresh window so a stalled SSR proxy or unreachable backend
// cannot pin the deduper open and freeze every 401-retried request behind
// it forever. 10 s matches the upstream JWT-refresh budget.
const REFRESH_TIMEOUT_MS = 10_000;

const refreshSession = async (): Promise<void> => {
  if (!refreshInFlight) {
    const request = axios
      .post(SSR_REFRESH_PATH, undefined, {
        withCredentials: true,
        timeout: REFRESH_TIMEOUT_MS,
      })
      .then(() => undefined);

    const timeout = new Promise<void>((_, reject) => {
      setTimeout(
        () => reject(new Error('refresh-timeout')),
        REFRESH_TIMEOUT_MS,
      );
    });

    refreshInFlight = Promise.race([request, timeout])
      .then(() => undefined)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
};

const isSafeRedirect = (raw: string): boolean => {
  // Only allow same-origin paths. Reject schemes (`http:`), protocol-relative
  // (`//evil.com`), and anything that is not a well-formed pathname.
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
    const data = error.response?.data as ErrorBody | undefined;
    error.message = resolveErrorMessage(data?.code, extractMessage(data));

    const original = error.config as RetryableConfig | undefined;
    const status = error.response?.status;
    const url = original?.url ?? '';
    const isAuthHop =
      url.includes(REFRESH_PATH) ||
      url.includes(SSR_REFRESH_PATH) ||
      url.includes(SIGN_OUT_PATH);

    if (status === 401 && original && !original._retry && !isAuthHop) {
      original._retry = true;
      try {
        await refreshSession();
        return apiClient.request(original);
      } catch (refreshErr) {
        if (typeof window !== 'undefined') {
          // Clear stale auth cookies BEFORE navigating. Without this the
          // expired JWT keeps round-tripping with the redirect, the SSR
          // auth layer treats the user as authenticated, and the anonymous
          // layout bounces them back — producing an infinite sign-in ↔
          // protected-route loop. Best-effort: ignore errors (the redirect
          // still happens).
          await axios
            .post(`${apiClient.defaults.baseURL ?? ''}${SIGN_OUT_PATH}`, undefined, {
              withCredentials: true,
            })
            .catch(() => undefined);
          const here = window.location.pathname + window.location.search;
          const onAuth = window.location.pathname.startsWith('/auth/');
          const safeHere = isSafeRedirect(here) ? here : '/';
          const target = onAuth ? '/auth/sign-in' : `/auth/sign-in?redirect=${encodeURIComponent(safeHere)}`;
          window.location.assign(target);
        }
        return Promise.reject(refreshErr);
      }
    }

    return Promise.reject(error);
  },
);
