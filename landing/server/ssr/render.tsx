import { createRequestHandler, renderRouterToString, RouterServer } from '@tanstack/react-router/ssr/server';
import type { RenderFnInput, RenderPayload } from './ssr.types';
import { createAppRouter } from '../../src/app/router/router';
import { AppShell } from '../../src/app/app';
import { buildHeadTags } from '../../src/shared/seo/seo';

export async function render(input: RenderFnInput): Promise<RenderPayload> {
  const t0 = Date.now();
  const request = new Request(`http://localhost${input.url}`);

  const handler = createRequestHandler({
    request,
    createRouter: () => createAppRouter(),
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
        <AppShell>
          <RouterServer router={params.router} />
        </AppShell>
      ),
    });

    const responseHtml = await response.text();

    const scriptMatches = responseHtml.match(
      /<script[^>]*class=['"]\$tsr['"][^>]*>[\s\S]*?<\/script>/g,
    );
    if (scriptMatches && scriptMatches.length > 0) {
      injectedScripts = scriptMatches.join('\n');
    } else if (routerInstance?.serverSsr) {
      routerInstance.serverSsr.setRenderFinished();
      const extractedScripts = await Promise.all(routerInstance.serverSsr.injectedHtml).then(
        (htmls: string[]) => htmls.join(''),
      );
      if (extractedScripts.length > 0) injectedScripts = extractedScripts;
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
        headTags: '',
        initialState: {},
        redirect: { status: response.status, location: redirectLocation },
      };
    }
  }

  let html = await response.text();
  if (html.startsWith('<!DOCTYPE html>')) {
    html = html.replace('<!DOCTYPE html>', '');
  }

  const headTags = buildHeadTags(input.url);
  const ssrMs = Date.now() - t0;
  // Fastify already logs request lifecycle; this is focused SSR/meta validation.
  console.log(
    JSON.stringify({
      msg: 'ssr_render',
      url: input.url,
      statusCode: response.status,
      ssrMs,
      headTagsChars: headTags.length,
    }),
  );

  return {
    html,
    headTags,
    initialState: {},
    injectedScripts,
    statusCode: response.status,
  };
}


