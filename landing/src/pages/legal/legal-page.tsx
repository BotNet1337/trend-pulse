import * as React from 'react';
import { Accordion, AccordionItem } from '@/shared/components/accordion';

export type LegalAccordionItem = {
  id: string;
  title: string;
  defaultOpen?: boolean;
  content: React.ReactNode;
};

export function LegalPage(props: {
  title: string;
  lastUpdated: string;
  intro?: React.ReactNode;
  top?: React.ReactNode;
  items: LegalAccordionItem[];
}) {
  if (import.meta.env.DEV) {
    try {
      if (!props.items.length) {
         
        console.warn('[landing] LegalPage has no items', { title: props.title });
      }
    } catch {
      // ignore
    }
  }

  return (
    <div className="pt-24 pb-16 px-6 lg:px-20">
      <div className="max-w-4xl mx-auto">
        <div className="mb-12">
          <h1 className="text-4xl md:text-5xl font-bold mb-4">{props.title}</h1>
          <p className="text-muted-foreground">Last updated: {props.lastUpdated}</p>
          {props.intro ? <div className="text-muted-foreground mt-4">{props.intro}</div> : null}
        </div>

        {props.top ? <div className="mb-12">{props.top}</div> : null}

        <Accordion>
          {props.items.map((item) => (
            <AccordionItem key={item.id} title={item.title} defaultOpen={item.defaultOpen}>
              {item.content}
            </AccordionItem>
          ))}
        </Accordion>
      </div>
    </div>
  );
}


