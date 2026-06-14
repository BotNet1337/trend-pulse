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
    <div role="alert" aria-live="polite" className="fs-card fs-upsell">
      <div>
        <p className="fs-upsell__title">
          Plan limit reached
          {currentPlan ? ` (current plan: ${currentPlan})` : ''}
        </p>
        <p className="fs-upsell__text">{message}</p>
      </div>
      <div className="fs-upsell__actions">
        {/* C5 billing route — stub link until billing UI is implemented */}
        <Link
          to="/billing"
          className="fs-btn fs-btn--primary fs-btn--sm"
          aria-label="Upgrade your plan"
        >
          Upgrade plan
        </Link>
      </div>
    </div>
  );
};
