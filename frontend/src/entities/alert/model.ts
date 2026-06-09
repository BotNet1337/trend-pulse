/**
 * Alert entity model — types derived from OpenAPI gen.types (C1 invariant).
 * Source of truth: backend schemas AlertRead / AlertListResponse.
 * Do NOT redeclare shapes manually; use the generated types.
 */

import type { components } from '@/shared/api/gen.types';

/** A persisted alert row with joined Cluster.topic. */
export type AlertRead = components['schemas']['AlertRead'];

/** Paginated response envelope for GET /alerts. */
export type AlertListResponse = components['schemas']['AlertListResponse'];

/** Delivery status values — keep in sync with backend constants. */
export type DeliveryStatus = 'pending' | 'delivered' | 'failed';

/** Stable query key for the alerts list. */
export const ALERTS_QUERY_KEY = ['alerts', 'list'] as const;

/** Stable query key factory for a single alert. */
export const alertQueryKey = (id: number) => ['alerts', 'detail', id] as const;
