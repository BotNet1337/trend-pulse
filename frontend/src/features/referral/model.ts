/**
 * Referral feature model — React Query hooks for GET /referral/me (TASK-046).
 */

import { useQuery } from '@tanstack/react-query';

import { getReferralMe, type ReferralMeResponse } from './api';

const REFERRAL_ME_QUERY_KEY = ['referral', 'me'] as const;

/**
 * useReferralMe — fetch the authenticated user's referral data.
 * Returns code, share link, and rewards list.
 */
export function useReferralMe() {
  return useQuery<ReferralMeResponse>({
    queryKey: REFERRAL_ME_QUERY_KEY,
    queryFn: getReferralMe,
  });
}
