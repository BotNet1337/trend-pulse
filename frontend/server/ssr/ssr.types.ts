export type RenderPayload = {
  html: string;
  initialState: Record<string, unknown>;
  dehydratedRouter?: unknown;
  injectedScripts?: string;
  redirect?: {
    location: string;
    status: number;
  };
};

import type { SerializedQuery } from '../../src/shared/ssr/initial-state.types'

export interface RenderContext {
  /**
   * Raw `Cookie` request header from the inbound SSR request. Forwarded to
   * the upstream API so that the httpOnly `fastapiusersauth` cookie
   * authenticates server-side prefetch calls.
   *
   * TrendPulse uses fastapi-users cookie transport — NOT Bearer tokens.
   * The previous `accessToken` field and its Bearer-injection logic have been
   * removed as part of TASK-029 (cookie-auth SSR fix).
   */
  cookieHeader?: string
}

export interface RenderFnInput {
  url: string;
  ctx: RenderContext;
}

export type RenderFn = (input: RenderFnInput) => Promise<RenderPayload>;

export type { SerializedQuery };
