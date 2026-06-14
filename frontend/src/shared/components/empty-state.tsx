/**
 * EmptyState — friendly empty list state with optional CTA.
 */

import React from 'react';
import { Button } from './button';

interface EmptyStateProps {
  title: string;
  description?: string;
  ctaLabel?: string;
  onCta?: () => void;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  ctaLabel,
  onCta,
}) => {
  return (
    <div className="fs-empty">
      <div className="fs-empty__icon" aria-hidden="true">
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M3 3v18h18" />
          <path d="m19 9-5 5-4-4-3 3" />
        </svg>
      </div>
      <h2 className="fs-empty__title">{title}</h2>
      {description && <p className="fs-empty__text">{description}</p>}
      {ctaLabel && onCta && (
        <Button type="button" onClick={onCta}>
          {ctaLabel}
        </Button>
      )}
    </div>
  );
};
