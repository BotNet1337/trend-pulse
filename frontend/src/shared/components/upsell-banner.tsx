/**
 * UpsellBanner — shown when backend returns 402 (quota exceeded).
 * Links to billing route (C5). Stub /billing link is acceptable until C5 ships.
 */

import React from 'react';
import { Link } from '@tanstack/react-router';

interface UpsellBannerProps {
  message?: string;
  /** Plan name from useCurrentUser (e.g. "free"). */
  currentPlan?: string;
}

const DEFAULT_MESSAGE =
  'You have reached the limit for your current plan. Upgrade to add more watchlists.';

export const UpsellBanner: React.FC<UpsellBannerProps> = ({
  message = DEFAULT_MESSAGE,
  currentPlan,
}) => {
  return (
    <div
      role="alert"
      aria-live="polite"
      className="rounded-lg border border-amber-400/50 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 flex flex-col gap-2 text-sm"
    >
      <p className="font-medium text-amber-800 dark:text-amber-300">
        Plan limit reached
        {currentPlan ? ` (current plan: ${currentPlan})` : ''}
      </p>
      <p className="text-amber-700 dark:text-amber-400">{message}</p>
      {/* C5 billing route — stub link until billing UI is implemented */}
      <Link
        to="/billing"
        className="inline-flex items-center gap-1 text-amber-800 dark:text-amber-300 underline underline-offset-2 font-medium hover:no-underline w-fit"
        aria-label="Upgrade your plan"
      >
        Upgrade plan
      </Link>
    </div>
  );
};
