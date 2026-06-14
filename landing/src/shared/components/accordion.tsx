import * as React from 'react';
import { ChevronDown } from 'lucide-react';

export function Accordion(props: { children: React.ReactNode; className?: string }) {
  return <div className={['grid gap-3.5', props.className].filter(Boolean).join(' ')}>{props.children}</div>;
}

export function AccordionItem(props: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [isOpen, setIsOpen] = React.useState(Boolean(props.defaultOpen));

  return (
    <div className="fs-glass overflow-hidden">
      <button
        type="button"
        onClick={() => {
          const next = !isOpen;
          setIsOpen(next);

          if (import.meta.env.DEV) {
            try {

              console.debug('[landing] accordion toggle', { title: props.title, open: next });
            } catch {
              // ignore
            }
          }
        }}
        className="w-full flex items-center justify-between gap-4 px-6 py-5 text-left hover:bg-white/[0.04] transition-colors"
        aria-expanded={isOpen}
      >
        <span className="font-semibold text-base">{props.title}</span>
        <ChevronDown
          className={[
            'h-[18px] w-[18px] flex-none transition-transform duration-200',
            isOpen ? 'rotate-180 text-[color:var(--aurora-cyan-bright)]' : 'text-[color:var(--aurora-text-faint)]',
          ].join(' ')}
        />
      </button>
      <div
        className={[
          'grid transition-[grid-template-rows] duration-300 ease-in-out',
          isOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]',
        ].join(' ')}
        aria-hidden={!isOpen}
      >
        <div className="overflow-hidden">
          <div
            className={[
              'px-6 pb-5 pt-0 text-sm text-muted-foreground space-y-4 transition-opacity duration-200',
              isOpen ? 'opacity-100' : 'opacity-0',
            ].join(' ')}
          >
            {props.children}
          </div>
        </div>
      </div>
    </div>
  );
}

