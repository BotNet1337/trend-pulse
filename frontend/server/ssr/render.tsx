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
import type { JwtUser } from '../../src/entities/user/model';
import type { CurrentUser } from '../../src/entities/viewer/model';

/**
 * Map a CurrentUser (from GET /users/me UserMeResponse) to the JwtUser shape
 * used by AuthStore. Mirrors the client-side `toJwtUser` in auth.provider.tsx.
 *
 * The `fastapiusersauth` JWT only carries `sub`/`aud`/`exp` — email and other
 * user data are NOT in the token and must come from /users/me.
 */
function toJwtUser(user: CurrentUser): JwtUser {
  return {
    userId: String(user.id),
    accountId: String(user.id),
    email: user.email,
    provider: 'cookie',
  };
}

export async function render(input: RenderFnInput): Promise<RenderPayload> {
  const requestUrl = new URL(input.url, 'http://localhost');

  // Prefetch BEFORE rendering so we can seed a server-side QueryClient with
  // the same data the client will hydrate from. Cookie is forwarded verbatim —
  // no Bearer-token lifting (TrendPulse is cookie-auth only).
  const queries = await runPrefetch({
    pathname: requestUrl.pathname,
    search: requestUrl.searchParams,
    cookieHeader: input.ctx.cookieHeader,
  });

  // Extract current user from prefetch results.
  // CURRENT_USER_QUERY_KEY = ['viewer', 'me'] (entities/viewer/model.ts).
  // The prefetch runner drops all queries on 401, so if the cookie is absent
  // or expired, queries = [] and ssrUser = null (anonymous render).
  const viewerEntry = queries.find(
    (q) => Array.isArray(q.key) && q.key[0] === 'viewer' && q.key[1] === 'me',
  );
  const ssrUser: JwtUser | null = viewerEntry
    ? toJwtUser(viewerEntry.data as CurrentUser)
    : null;

  const auth = createAuthStore({ user: ssrUser });
  const alert = createAlertStore();

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

  // SECURITY: ssrUser is derived from the Zod-validated UserMeResponse —
  // only safe fields (userId, accountId, email, provider) reach the browser.
  // `queries` carries server-prefetched cache entries; payloads are responses
  // from authenticated API calls scoped to the current user.
  const initialState: Record<string, unknown> = {
    user: ssrUser,
    queries,
  };

  if (html.startsWith('<!DOCTYPE html>')) {
    html = html.replace('<!DOCTYPE html>', '');
  }

  return { html, initialState, dehydratedRouter: null, injectedScripts };
}
