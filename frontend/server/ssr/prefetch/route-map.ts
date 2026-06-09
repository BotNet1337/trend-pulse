import {
  fetchCalendarPosts,
  fetchChannelsList,
  fetchDashboard,
  fetchModerationQueue,
  fetchPostById,
  fetchPostsList,
  fetchWorkspaceById,
  fetchWorkspacesList,
} from './fetchers';
import type { Fetcher } from './types';

/**
 * Map of TanStack Router path patterns → atomic fetchers to run for SSR
 * hydration. More specific patterns MUST come before less specific ones —
 * the matcher returns the first hit (`matchRoute`).
 *
 * Composition rules (from TASK-036):
 * - any authorised route → workspaces list (sidebar / picker is global).
 * - `:workspaceId` present → workspace detail + channels list (every
 *   workspace screen renders the channel sidebar).
 * - `/posts` route → posts list with filters from `?search=…` etc.
 * - `/calendar` route → calendar grid (range derived from `?anchor=YYYY-MM`).
 * - `:postId` present → post detail (publications come embedded inside
 *   `PostAggregate.publications[]`, so no separate publications fetcher).
 *
 * Workspace-wide publications (`fetchWorkspacePublications`) is exported by
 * `fetchers.ts` but intentionally NOT in any default composition yet —
 * payload size matters (worst case 20× publication rows on every workspace
 * page load) and no current screen reads from that key. Plug it into a
 * pattern when a workspace-wide publications view ships.
 */
export const PREFETCH_ROUTE_PATTERNS: readonly string[] = [
  '/workspaces/$id/posts/$postId/publications/$publicationId',
  '/workspaces/$id/posts/$postId',
  '/workspaces/$id/posts',
  '/workspaces/$id/calendar',
  '/workspaces/$id/channels',
  '/workspaces/$id/dashboard',
  '/workspaces/$id',
  '/workspaces',
  '/moderation',
];

export const PREFETCH_ROUTES: Record<string, Fetcher[]> = {
  // Admin moderation queue (TASK-072) — global, no workspace context. Just the
  // queue; sidebar admin nav needs no workspace data.
  '/moderation': [fetchModerationQueue],
  '/workspaces': [fetchWorkspacesList],
  '/workspaces/$id': [fetchWorkspacesList, fetchWorkspaceById, fetchChannelsList],
  '/workspaces/$id/channels': [
    fetchWorkspacesList,
    fetchWorkspaceById,
    fetchChannelsList,
  ],
  '/workspaces/$id/dashboard': [
    fetchWorkspacesList,
    fetchWorkspaceById,
    fetchChannelsList,
    fetchDashboard,
  ],
  '/workspaces/$id/posts': [
    fetchWorkspacesList,
    fetchWorkspaceById,
    fetchChannelsList,
    fetchPostsList,
  ],
  '/workspaces/$id/calendar': [
    fetchWorkspacesList,
    fetchWorkspaceById,
    fetchChannelsList,
    fetchCalendarPosts,
  ],
  '/workspaces/$id/posts/$postId': [
    fetchWorkspacesList,
    fetchWorkspaceById,
    fetchChannelsList,
    fetchPostById,
  ],
  '/workspaces/$id/posts/$postId/publications/$publicationId': [
    fetchWorkspacesList,
    fetchWorkspaceById,
    fetchChannelsList,
    fetchPostById,
  ],
};

/**
 * Map TanStack Router param names (from the patterns above) to the keys our
 * fetchers expect. Patterns use `$id` for the workspace UUID for historical
 * reasons but fetchers read `params.workspaceId` — translate here so route
 * authors can keep using the established TanStack convention.
 */
export const PARAM_ALIASES: Record<string, string> = {
  id: 'workspaceId',
};
