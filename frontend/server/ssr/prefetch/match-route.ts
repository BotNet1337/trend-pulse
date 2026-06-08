/**
 * Tiny URL-to-pattern matcher tailored to TanStack Router's `$param` syntax.
 *
 * We do NOT call into TanStack Router on the server here — pulling the full
 * router state for prefetch is overkill, and a hand-rolled matcher keeps the
 * SSR critical path branch-free of router internals.
 */

export interface MatchedRoute {
  pattern: string;
  params: Record<string, string>;
}

const splitSegments = (path: string): string[] =>
  path.replace(/^\/+/, '').replace(/\/+$/, '').split('/').filter(Boolean);

function matchOne(pattern: string, pathname: string): MatchedRoute | null {
  const patternSegments = splitSegments(pattern);
  const pathSegments = splitSegments(pathname);

  if (patternSegments.length !== pathSegments.length) {
    return null;
  }

  const params: Record<string, string> = {};

  for (let i = 0; i < patternSegments.length; i += 1) {
    const patternSeg = patternSegments[i];
    const pathSeg = pathSegments[i];

    if (patternSeg.startsWith('$')) {
      const name = patternSeg.slice(1);
      if (!name || !pathSeg) return null;
      params[name] = decodeURIComponent(pathSeg);
      continue;
    }

    if (patternSeg !== pathSeg) {
      return null;
    }
  }

  return { pattern, params };
}

/**
 * Match `pathname` against the given list of patterns. Patterns are checked
 * **in the order provided** — callers are expected to list more specific
 * patterns (e.g. `/workspaces/$id/posts/$postId`) before less specific ones
 * (`/workspaces/$id`) so the most specific match wins.
 */
export function matchRoute(
  pathname: string,
  patterns: readonly string[],
): MatchedRoute | null {
  for (const pattern of patterns) {
    const matched = matchOne(pattern, pathname);
    if (matched) return matched;
  }
  return null;
}
