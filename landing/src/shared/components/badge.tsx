import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/shared/utils/utils';

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-aurora-button text-primary-foreground shadow-[0_4px_18px_rgba(99,102,241,0.4)]',
        // Glass pill — matches the mockup .hero-badge.
        secondary: 'border border-white/10 bg-white/5 text-muted-foreground backdrop-blur-md',
        outline: 'border-white/10 bg-white/5 text-muted-foreground backdrop-blur-md',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}


