import {
  listWorkspaces,
  WORKSPACES_LIST_PAGE_DEFAULTS,
  type ListWorkspacesQuery,
} from '../../../src/features/workspaces/list/api';
import { workspaceListQueryKey } from '../../../src/features/workspaces/list/model';
import { findWorkspaceById } from '../../../src/features/workspaces/find/api';
import { workspaceQueryKey } from '../../../src/features/workspaces/find/model';
import {
  listChannels,
  CHANNELS_LIST_PAGE_DEFAULTS,
  type ListChannelsQuery,
} from '../../../src/features/channels/list/api';
import { channelsListQueryKey } from '../../../src/features/channels/list/model';
import {
  listPosts,
  POSTS_LIST_PAGE_DEFAULTS,
  type ListPostsQuery,
} from '../../../src/features/posts/list/api';
import { postsListQueryKey } from '../../../src/features/posts/list/model';
import { findPostById } from '../../../src/features/posts/find/api';
import { postQueryKey } from '../../../src/features/posts/find/model';
import { listCalendarPosts } from '../../../src/features/calendar/list/api';
import { calendarPostsQueryKey } from '../../../src/features/calendar/list/model';
import {
  listWorkspacePublications,
  type ListWorkspacePublicationsQuery,
} from '../../../src/features/publications/list/api';
import { workspacePublicationsListQueryKey } from '../../../src/features/publications/list/model';
import {
  getDashboard,
  dashboardQueryFromRange,
} from '../../../src/features/analytics/dashboard/api';
import { dashboardQueryKey } from '../../../src/features/analytics/dashboard/model';
import { defaultDateRange } from '../../../src/entities/analytics';
import {
  getModerationQueue,
  MODERATION_QUEUE_PAGE_DEFAULTS,
} from '../../../src/features/moderation/queue/api';
import { moderationQueueQueryKey } from '../../../src/features/moderation/queue/model';
import type { Fetcher } from './types';

const parsePostsFilters = (search: URLSearchParams): ListPostsQuery => {
  const csv = (key: string): string[] | undefined => {
    const raw = search.get(key);
    if (!raw) return undefined;
    const items = raw.split(',').map((s) => s.trim()).filter(Boolean);
    return items.length > 0 ? items : undefined;
  };
  const single = (key: string): string | undefined => search.get(key) ?? undefined;
  const num = (key: string): number | undefined => {
    const raw = search.get(key);
    if (!raw) return undefined;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : undefined;
  };

  const query: ListPostsQuery = {};

  const offset = num('offset');
  if (offset !== undefined) query.offset = offset;
  const limit = num('limit');
  if (limit !== undefined) query.limit = limit;

  const searchTerm = single('search');
  if (searchTerm) query.search = searchTerm;

  const status = csv('status');
  if (status) query.status = status as ListPostsQuery['status'];
  const tags = csv('tags');
  if (tags) query.tags = tags;
  const postType = csv('postType');
  if (postType) query.postType = postType as ListPostsQuery['postType'];
  const publicationStatus = csv('publicationStatus');
  if (publicationStatus)
    query.publicationStatus = publicationStatus as ListPostsQuery['publicationStatus'];

  const channelId = single('channelId');
  if (channelId) query.channelId = channelId;
  const authorId = single('authorId');
  if (authorId) query.authorId = authorId;

  const sortBy = single('sortBy');
  if (sortBy) query.sortBy = sortBy as ListPostsQuery['sortBy'];
  const sortOrder = single('sortOrder');
  if (sortOrder) query.sortOrder = sortOrder as ListPostsQuery['sortOrder'];

  const rangeFrom = single('rangeFrom');
  if (rangeFrom) query.rangeFrom = rangeFrom;
  const rangeTo = single('rangeTo');
  if (rangeTo) query.rangeTo = rangeTo;

  const cursor = single('cursor');
  if (cursor) query.cursor = cursor;

  return query;
};

const parseAnchor = (search: URLSearchParams): Date => {
  const raw = search.get('anchor');
  if (!raw) return new Date();
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
};

export const fetchWorkspacesList: Fetcher = async ({ api }) => {
  const query: ListWorkspacesQuery = { ...WORKSPACES_LIST_PAGE_DEFAULTS };
  const data = await listWorkspaces(query, api);
  return { key: workspaceListQueryKey(query), data };
};

export const fetchWorkspaceById: Fetcher = async ({ api, params }) => {
  const workspaceId = params.workspaceId;
  if (!workspaceId) return null;
  const data = await findWorkspaceById({ id: workspaceId }, api);
  return { key: workspaceQueryKey(workspaceId), data };
};

export const fetchChannelsList: Fetcher = async ({ api, params }) => {
  const workspaceId = params.workspaceId;
  if (!workspaceId) return null;
  const query: ListChannelsQuery = { ...CHANNELS_LIST_PAGE_DEFAULTS };
  const data = await listChannels({ workspaceId }, query, api);
  return { key: channelsListQueryKey(workspaceId, query), data };
};

export const fetchPostsList: Fetcher = async ({ api, params, search }) => {
  const workspaceId = params.workspaceId;
  if (!workspaceId) return null;
  // Layer URL filters on top of the page's defaults so the cache key the
  // server seeds matches the one the React component builds on first render
  // (`limit`, `sortBy`, `sortOrder`). Without this the hydrated data sits in
  // the cache under a stale key and the page renders skeletons until the
  // client refetch lands.
  const query: ListPostsQuery = {
    ...POSTS_LIST_PAGE_DEFAULTS,
    ...parsePostsFilters(search),
  };
  const data = await listPosts({ workspaceId }, query, api);
  return { key: postsListQueryKey(workspaceId, query), data };
};

export const fetchPostById: Fetcher = async ({ api, params }) => {
  const workspaceId = params.workspaceId;
  const postId = params.postId;
  if (!workspaceId || !postId) return null;
  const data = await findPostById({ workspaceId, id: postId }, api);
  return { key: postQueryKey(workspaceId, postId), data };
};

export const fetchCalendarPosts: Fetcher = async ({ api, params, search }) => {
  const workspaceId = params.workspaceId;
  if (!workspaceId) return null;
  const anchor = parseAnchor(search);
  const channelId = search.get('channelId') ?? undefined;
  const data = await listCalendarPosts({ workspaceId }, { anchor, channelId }, api);
  return { key: calendarPostsQueryKey(workspaceId, { anchor, channelId }), data };
};

/**
 * SSR-hydrate the global moderation queue (TASK-072). No path params — the
 * queue is cross-workspace. The query key MUST match
 * `moderationQueueQueryKey(MODERATION_QUEUE_PAGE_DEFAULTS)` byte-for-byte so the
 * client hook hydrates instead of refetching (same rule as the other fetchers).
 * A 403 (non-admin) propagates as an axios error → the runner drops this entry;
 * the client then sees the forbidden state on first paint.
 */
export const fetchModerationQueue: Fetcher = async ({ api }) => {
  const data = await getModerationQueue(MODERATION_QUEUE_PAGE_DEFAULTS, api);
  return {
    key: moderationQueueQueryKey(MODERATION_QUEUE_PAGE_DEFAULTS),
    data,
  };
};

export const fetchWorkspacePublications: Fetcher = async ({ api, params, search }) => {
  const workspaceId = params.workspaceId;
  if (!workspaceId) return null;
  const channelId = search.get('channelId') ?? undefined;
  const query: ListWorkspacePublicationsQuery = channelId ? { channelId } : {};
  const data = await listWorkspacePublications({ workspaceId }, query, api);
  return { key: workspacePublicationsListQueryKey(workspaceId, query), data };
};

/**
 * Analytics dashboard prefetch. Uses the same default range
 * (`defaultDateRange()`) the page opens with, and keys via the shared
 * `dashboardQueryKey` so the hydrated entry lands under the runtime key the
 * `useDashboard` hook builds on first render (the key is day-bucketed, so a
 * sub-second server/client time skew can't drift it). The raw `from`/`to`
 * sent to the API are the full ISO datetime bounds.
 */
export const fetchDashboard: Fetcher = async ({ api, params }) => {
  const workspaceId = params.workspaceId;
  if (!workspaceId) return null;
  const range = defaultDateRange();
  const data = await getDashboard(
    { workspaceId },
    dashboardQueryFromRange(range),
    api,
  );
  return { key: dashboardQueryKey(workspaceId, range), data };
};
