import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/shared/utils/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full font-semibold transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        // Aurora gradient CTA — pill + glow, matches the mockup .btn-primary.
        default:
          'bg-aurora-button text-primary-foreground shadow-[0_4px_24px_rgba(99,102,241,0.35)] hover:bg-aurora-button-hover hover:-translate-y-0.5 hover:shadow-[0_8px_32px_rgba(99,102,241,0.45)] active:translate-y-0',
        brand:
          'bg-aurora-button text-primary-foreground shadow-[0_4px_24px_rgba(99,102,241,0.35)] hover:bg-aurora-button-hover hover:-translate-y-0.5 hover:shadow-[0_8px_32px_rgba(99,102,241,0.45)] active:translate-y-0',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        // Glass ghost — matches the mockup .btn-ghost.
        outline:
          'bg-white/5 text-foreground border border-white/[0.18] hover:bg-white/[0.08] hover:border-white/30 hover:-translate-y-0.5',
        ghost: 'hover:bg-white/[0.06] hover:text-foreground',
      },
      size: {
        default: 'h-11 px-6 text-base',
        sm: 'h-9 px-5 text-sm',
        lg: 'h-12 px-7 text-base',
        icon: 'h-10 w-10 p-0',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : 'button';

  return (
    <Comp
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button };
