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
    <div className="flex flex-col items-center justify-center gap-4 py-16 px-4 text-center">
      <div className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold text-foreground">{title}</h2>
        {description && (
          <p className="text-sm text-muted-foreground max-w-sm">{description}</p>
        )}
      </div>
      {ctaLabel && onCta && (
        <Button type="button" onClick={onCta}>
          {ctaLabel}
        </Button>
      )}
    </div>
  );
};
