import axios, { type AxiosError } from 'axios';
import { resolveErrorMessage } from '@/shared/lib';

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

// TrendPulse API client — cookie-auth (httpOnly, set by backend fastapi-users).
// baseURL: '/api' → nginx strips /api prefix and proxies to backend.
// withCredentials: true → browser sends the fastapiusersauth cookie.
// No Bearer tokens, no localStorage. No refresh endpoint (TrendPulse uses
// session cookies; on 401 the user is redirected to /auth/sign-in).
export const apiClient = axios.create({
  baseURL: '/api',
  withCredentials: true,
});

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
    const data = error.response?.data as ErrorBody | undefined;
    error.message = resolveErrorMessage(data?.code, extractMessage(data));

    const status = error.response?.status;
    const url = error.config?.url ?? '';

    // On 401: redirect to sign-in. Skip for the logout endpoint itself to
    // avoid redirect loops. No refresh — TrendPulse uses cookie-auth without
    // a refresh token endpoint.
    if (status === 401 && !url.includes(LOGOUT_PATH) && typeof window !== 'undefined') {
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
