import * as React from 'react';
import { ChevronRight } from 'lucide-react';

export function LegalLayout(
  props: React.PropsWithChildren<{
    title: string;
    lastUpdated: string;
    sections: { id: string; title: string }[];
  }>,
) {
  const [activeSection, setActiveSection] = React.useState('');

  return (
    <div className="pt-24 pb-16">
      <div className="max-w-7xl mx-auto px-6 lg:px-20">
        <div className="mb-12">
          <h1 className="text-4xl font-bold mb-4">{props.title}</h1>
          <p className="text-sm text-muted-foreground">Last updated: {props.lastUpdated}</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-12">
          <aside className="hidden lg:block">
            <div className="sticky top-24">
              <h3 className="mb-4">Table of Contents</h3>
              <nav className="space-y-2">
                {props.sections.map((section) => (
                  <a
                    key={section.id}
                    href={`#${section.id}`}
                    className={`flex items-center text-sm py-1 transition-colors ${
                      activeSection === section.id ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
                    }`}
                    onClick={() => setActiveSection(section.id)}
                  >
                    <ChevronRight className="h-4 w-4 mr-1" />
                    {section.title}
                  </a>
                ))}
              </nav>
            </div>
          </aside>

          <div className="lg:hidden mb-8">
            <details className="bg-card border border-border rounded-lg p-4">
              <summary className="cursor-pointer font-medium">Table of Contents</summary>
              <nav className="space-y-2 mt-4">
                {props.sections.map((section) => (
                  <a
                    key={section.id}
                    href={`#${section.id}`}
                    className="block text-sm text-muted-foreground hover:text-foreground py-1"
                    onClick={() => setActiveSection(section.id)}
                  >
                    {section.title}
                  </a>
                ))}
              </nav>
            </details>
          </div>

          <div className="lg:col-span-3">
            <div className="prose prose-neutral dark:prose-invert max-w-none">
              {props.children}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}


