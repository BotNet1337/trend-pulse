import { describe, expect, it } from 'vitest';
import { matchRoute } from '../../../../../server/ssr/prefetch/match-route';
import { PREFETCH_ROUTE_PATTERNS } from '../../../../../server/ssr/prefetch/route-map';

describe('matchRoute', () => {
  it('matches the workspaces list', () => {
    const result = matchRoute('/workspaces', PREFETCH_ROUTE_PATTERNS);
    expect(result).toEqual({ pattern: '/workspaces', params: {} });
  });

  it('matches workspace detail and extracts the id param', () => {
    const result = matchRoute(
      '/workspaces/abc-123',
      PREFETCH_ROUTE_PATTERNS,
    );
    expect(result).toEqual({
      pattern: '/workspaces/$id',
      params: { id: 'abc-123' },
    });
  });

  it('matches workspace channels', () => {
    const result = matchRoute(
      '/workspaces/abc-123/channels',
      PREFETCH_ROUTE_PATTERNS,
    );
    expect(result).toEqual({
      pattern: '/workspaces/$id/channels',
      params: { id: 'abc-123' },
    });
  });

  it('matches posts list', () => {
    const result = matchRoute(
      '/workspaces/abc-123/posts',
      PREFETCH_ROUTE_PATTERNS,
    );
    expect(result).toEqual({
      pattern: '/workspaces/$id/posts',
      params: { id: 'abc-123' },
    });
  });

  it('matches calendar', () => {
    const result = matchRoute(
      '/workspaces/abc-123/calendar',
      PREFETCH_ROUTE_PATTERNS,
    );
    expect(result).toEqual({
      pattern: '/workspaces/$id/calendar',
      params: { id: 'abc-123' },
    });
  });

  it('prefers post detail over workspace detail when both could match', () => {
    const result = matchRoute(
      '/workspaces/ws/posts/post-1',
      PREFETCH_ROUTE_PATTERNS,
    );
    expect(result).toEqual({
      pattern: '/workspaces/$id/posts/$postId',
      params: { id: 'ws', postId: 'post-1' },
    });
  });

  it('matches publication detail', () => {
    const result = matchRoute(
      '/workspaces/ws/posts/post-1/publications/pub-1',
      PREFETCH_ROUTE_PATTERNS,
    );
    expect(result).toEqual({
      pattern: '/workspaces/$id/posts/$postId/publications/$publicationId',
      params: { id: 'ws', postId: 'post-1', publicationId: 'pub-1' },
    });
  });

  it('returns null for unknown paths', () => {
    expect(matchRoute('/auth/sign-in', PREFETCH_ROUTE_PATTERNS)).toBeNull();
    expect(matchRoute('/', PREFETCH_ROUTE_PATTERNS)).toBeNull();
  });

  it('decodes URI-encoded segment values', () => {
    const result = matchRoute(
      '/workspaces/my%20ws',
      PREFETCH_ROUTE_PATTERNS,
    );
    expect(result?.params.id).toBe('my ws');
  });

  it('does not match longer paths against shorter patterns', () => {
    const result = matchRoute(
      '/workspaces/abc/extra/segment',
      ['/workspaces/$id'],
    );
    expect(result).toBeNull();
  });
});
