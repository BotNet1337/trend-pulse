export type RenderPayload = {
  html: string;
  initialState: Record<string, unknown>;
  dehydratedRouter?: unknown; // Using unknown to avoid strict dependency typing here, or import DehydratedRouter
  injectedScripts?: string;
  redirect?: {
    location: string;
    status: number;
  };
};

import type { JwtUser } from '../../src/entities/user/model'
import type { SerializedQuery } from '../../src/shared/ssr/initial-state.types'

export interface RenderContext {
  user?: JwtUser | null
  /**
   * `access_token` extracted from the inbound cookies. SSR prefetch stamps it
   * as `Authorization: Bearer …` on upstream calls — the API only accepts
   * Bearer tokens (`ExtractJwt.fromAuthHeaderAsBearerToken`), so forwarding
   * the raw `Cookie` header alone gets every SSR fetcher 401'd.
   */
  accessToken?: string
}

export interface RenderFnInput {
  url: string;
  ctx: RenderContext;
}

export type RenderFn = (input: RenderFnInput) => Promise<RenderPayload>;

export type { SerializedQuery };
