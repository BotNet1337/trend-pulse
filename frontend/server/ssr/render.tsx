import React from 'react';
import { renderRouterToString, RouterServer, createRequestHandler } from '@tanstack/react-router/ssr/server';
import App from '../../src/app/app';
import { createAuthStore } from '../../src/app/stores/auth.store';
import { createAlertStore } from '../../src/app/stores/alert.store';
import { createAppRouter } from '../../src/app/router';
import { createQueryClient } from '../../src/app/providers/query-client';
import { hydrateQueryCache } from '../../src/app/hydrate-query-cache';
import type { RenderFnInput, RenderPayload } from './ssr.types';
import { runPrefetch } from './prefetch';

export async function render(input: RenderFnInput): Promise<RenderPayload> {
  // input.ctx.user is already Zod-filtered upstream (auth.plugin.ts) — no
  // raw JWT fields, no `[key: string]: unknown` wildcard. Pass through.
  const auth = createAuthStore({ user: input.ctx.user ?? null });
  const alert = createAlertStore();

  // Prefetch BEFORE rendering so we can seed a server-side QueryClient with
  // the same data the client will hydrate from. Without this seeding, hooks
  // like `useWorkspace`/`useChannels` return `data: undefined` during SSR
  // (empty cache), components branch on `workspace && (...)`, and the server
  // emits a different DOM than the client renders post-hydration — exactly
  // the WorkspaceTopBar `flex-1` vs `w-px h-6 bg-border mx-3` mismatch we
  // were chasing.
  const requestUrl = new URL(input.url, 'http://localhost');
  const queries = await runPrefetch({
    pathname: requestUrl.pathname,
    search: requestUrl.searchParams,
    accessToken: input.ctx.accessToken,
  });

  const queryClient = createQueryClient();
  hydrateQueryCache(queryClient, queries);

  const request = new Request(`http://localhost${input.url}`);

  const handler = createRequestHandler({
    request,
    createRouter: () => createAppRouter(auth),
  });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let routerInstance: any = null;
  let injectedScripts = '';

  const response = await handler(async (params) => {
    routerInstance = params.router;

    const response = await renderRouterToString({
      responseHeaders: params.responseHeaders,
      router: params.router,
      children: (
        <App auth={auth} alert={alert} queryClient={queryClient}>
          <RouterServer router={params.router} />
        </App>
      ),
    });

    const responseHtml = await response.text();

    const scriptMatches = responseHtml.match(/<script[^>]*class=['"]\$tsr['"][^>]*>[\s\S]*?<\/script>/g);
    if (scriptMatches && scriptMatches.length > 0) {
      injectedScripts = scriptMatches.join('\n');
    } else {
      routerInstance.serverSsr!.setRenderFinished();
      const extractedScripts = await Promise.all(routerInstance.serverSsr!.injectedHtml).then(
        (htmls: string[]) => htmls.join(''),
      );

      if (extractedScripts.length > 0) {
        injectedScripts = extractedScripts;
      }
    }

    return new Response(responseHtml, {
      status: response.status,
      headers: response.headers,
    });
  });

  if (response.status >= 300 && response.status < 400) {
    const location = response.headers.get('Location');
    if (location) {
      const redirectLocation = location.startsWith('http')
        ? new URL(location).pathname + new URL(location).search
        : location;

      return {
        html: '',
        initialState: {},
        redirect: {
          status: response.status as number,
          location: redirectLocation,
        },
      };
    }
  }

  let html = await response.text();

  // SECURITY (TASK-AUDIT-RELEASE-1 / C7):
  // `input.ctx.user` is already Zod-validated `JwtUser | null` — only safe
  // fields (userId, accountId, email, provider) reach the browser.
  // `queries` carries server-prefetched cache entries; payloads are responses
  // from authenticated API calls scoped to the current user.
  const initialState: Record<string, unknown> = {
    user: input.ctx.user ?? null,
    queries,
  };

  if (html.startsWith('<!DOCTYPE html>')) {
    html = html.replace('<!DOCTYPE html>', '');
  }

  return { html, initialState, dehydratedRouter: null, injectedScripts };
}
