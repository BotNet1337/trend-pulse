import * as React from 'react';
import { ChevronDown } from 'lucide-react';

export function Accordion(props: { children: React.ReactNode; className?: string }) {
  return <div className={['space-y-4', props.className].filter(Boolean).join(' ')}>{props.children}</div>;
}

export function AccordionItem(props: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [isOpen, setIsOpen] = React.useState(Boolean(props.defaultOpen));

  return (
    <div className="border border-border rounded-lg overflow-hidden bg-card">
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
        className="w-full flex items-center justify-between p-6 text-left hover:bg-muted/50 transition-colors"
        aria-expanded={isOpen}
      >
        <span className="font-semibold text-lg">{props.title}</span>
        <ChevronDown
          className={[
            'h-5 w-5 text-muted-foreground transition-transform duration-200',
            isOpen ? 'rotate-180' : '',
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
              'px-6 pb-6 pt-2 text-muted-foreground space-y-4 transition-opacity duration-200',
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

