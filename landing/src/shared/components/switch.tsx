import * as React from 'react';
import { cn } from '@/shared/utils/utils';

export interface SwitchProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  checked?: boolean;
  disabled?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

export function Switch({ checked = false, disabled, onCheckedChange, className, ...props }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => {
        if (disabled) return;
        onCheckedChange?.(!checked);
      }}
      className={cn(
        'inline-flex h-6 w-11 items-center rounded-full border border-border transition-colors',
        checked ? 'bg-primary' : 'bg-switch-background',
        disabled ? 'opacity-60' : 'cursor-pointer',
        className,
      )}
      {...props}
    >
      <span
        className={cn(
          'inline-block h-5 w-5 rounded-full bg-background shadow transition-transform',
          checked ? 'translate-x-5' : 'translate-x-0.5',
        )}
      />
    </button>
  );
}


