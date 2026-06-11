export type RenderPayload = {
  html: string;
  headTags: string;
  initialState: Record<string, unknown>;
  injectedScripts?: string;
  statusCode?: number;
  redirect?: {
    location: string;
    status: number;
  };
};

import type { CaseItem } from '../../src/shared/cases/types';

export interface RenderContext {
  requestId?: string;
}

export interface RenderFnInput {
  url: string;
  ctx: RenderContext;
  /** TASK-067: proof-of-speed cases fetched server-side (empty = section hidden). */
  cases?: CaseItem[];
}

export type RenderFn = (input: RenderFnInput) => Promise<RenderPayload>;


