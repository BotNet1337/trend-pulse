/**
 * Referral program API — GET /referral/me (TASK-046).
 *
 * Returns the authenticated user's referral code, share link, and earned rewards.
 * Cookie-auth (httpOnly); no tokens in localStorage/URL/logs.
 */

import { apiClient } from '@/shared/api';
import type { components } from '@/shared/api/gen.types';

export type ReferralMeResponse = components['schemas']['ReferralMeRead'];
export type ReferralRewardItem = components['schemas']['ReferralRewardRead'];

export const referralMePath = '/referral/me' as const;

/** GET /referral/me — fetch referral code, share link, and rewards list. */
export async function getReferralMe(): Promise<ReferralMeResponse> {
  const response = await apiClient.get<ReferralMeResponse>(referralMePath);
  return response.data;
}
