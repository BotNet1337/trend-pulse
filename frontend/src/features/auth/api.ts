/**
 * Auth feature API — wraps TrendPulse auth endpoints.
 *
 * Contracts (from task-003 / TASK-014):
 *  - register:  POST /auth/register          JSON { email, password }
 *  - login:     POST /auth/jwt/login         form-urlencoded username + password
 *  - logout:    POST /auth/jwt/logout        (no body)
 *  - google:    browser redirect to /api/auth/google/authorize (NOT fetch)
 *
 * Cookie-auth: httpOnly cookie set/cleared by backend; never read in JS.
 * withCredentials: true is set on apiClient (shared/api/client.ts).
 */

import { apiClient } from '@/shared/api';

export interface RegisterPayload {
  email: string;
  password: string;
  /**
   * Optional referral code from a share link (?ref=CODE).
   * Named 'referrer_code' (not 'ref_code') to avoid colliding with the
   * backend User.ref_code ORM column (TASK-046 G2 fix).
   */
  referrer_code?: string;
  /**
   * Google reCAPTCHA v2 client token. Present only in prod (the widget renders
   * when VITE_RECAPTCHA_SITE_KEY is set); the backend verifies it and rejects
   * sign-up on failure. Omitted in local dev where reCAPTCHA is OFF.
   */
  recaptcha_token?: string;
}

/** POST /auth/register — creates a new user. */
export async function register(payload: RegisterPayload): Promise<void> {
  await apiClient.post('/auth/register', payload);
}

export interface LoginPayload {
  email: string;
  password: string;
}

/**
 * POST /auth/jwt/login — form-urlencoded (fastapi-users OAuth2PasswordRequestForm).
 * Sets httpOnly fastapiusersauth cookie on success.
 */
export async function login(payload: LoginPayload): Promise<void> {
  const form = new URLSearchParams();
  form.set('username', payload.email);
  form.set('password', payload.password);
  await apiClient.post('/auth/jwt/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
}

/** POST /auth/jwt/logout — clears the httpOnly auth cookie. */
export async function logout(): Promise<void> {
  await apiClient.post('/auth/jwt/logout');
}

/**
 * Initiate Google OAuth — full browser redirect (NOT fetch).
 * No secrets on the frontend: redirect_uri and client_id live on backend.
 * /api/v1 = nginx strip-prefix /api/ + backend /v1 version prefix (TASK-030/ADR-007).
 */
export function navigateToGoogleAuth(): void {
  window.location.assign('/api/v1/auth/google/authorize');
}
