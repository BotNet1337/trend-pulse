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

export interface RenderContext {
  requestId?: string;
}

export interface RenderFnInput {
  url: string;
  ctx: RenderContext;
}

export type RenderFn = (input: RenderFnInput) => Promise<RenderPayload>;


