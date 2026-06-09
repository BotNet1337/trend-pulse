import type { RenderPayload } from './ssr.types.ts';

function safeJsonSerialize(value: unknown): string {
  // prevent "</script>" injection
  return JSON.stringify(value).replaceAll('</', '<\\/');
}

export function buildHtml(template: string, payload: RenderPayload): string {
  const serializedState = safeJsonSerialize(payload.initialState);
  const initialStateScript = `<script>window.__INITIAL_STATE__=${serializedState}</script>`;

  const appHtml = payload.html.trim();
  const scripts = payload.injectedScripts || '';

  return template
    .replace('<!--head-tags-->', payload.headTags ?? '')
    .replace('<!--app-html-->', appHtml)
    .replace('<!--initial-state-->', `${initialStateScript}\n${scripts}`);
}


