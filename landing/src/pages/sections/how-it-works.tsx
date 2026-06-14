import { Bell, Eye, Search } from 'lucide-react';
import { SITE } from '@/shared/site/constants';

export function HowItWorksSection() {
  const steps = [
    {
      icon: Search,
      title: 'Pick your topics & channels',
      description:
        'Choose the public Telegram channels you want to track and define the topics that matter to you — crypto, politics, tech, or anything else.',
    },
    {
      icon: Eye,
      title: 'We watch continuously',
      description:
        `${SITE.brandName} continuously scans public channels for emerging patterns, measuring velocity and spread across your channel list in real time.`,
    },
    {
      icon: Bell,
      title: 'Get alerted instantly',
      description:
        'When a topic crosses the viral threshold, you receive an alert with score, channel count, and timestamp — via Telegram or webhook.',
    },
  ];

  return (
    <section id="how-it-works" className="py-24 px-6 lg:px-20 bg-muted/20 snap-start scroll-mt-16">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">How it works</h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Get started with {SITE.brandName} in three simple steps
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 relative">
          <div
            className="hidden md:block absolute left-0 right-0 h-0.5 bg-border -translate-y-1/2"
            style={{ top: '80px' }}
          />

          {steps.map((step, index) => {
            const Icon = step.icon;
            return (
              <div key={step.title} className="group relative">
                <div className="bg-card border border-border rounded-lg p-8 text-center relative z-10 transition-all hover:shadow-md hover:border-primary/50 hover:-translate-y-0.5">
                  <div className="w-16 h-16 bg-aurora-button text-primary-foreground rounded-full flex items-center justify-center mx-auto mb-4 text-xl font-bold shadow-brand">
                    {index + 1}
                  </div>
                  <div className="w-12 h-12 bg-primary/10 rounded-lg flex items-center justify-center mx-auto mb-4 transition-colors group-hover:bg-primary/20">
                    <Icon className="h-6 w-6 text-primary" aria-hidden="true" />
                  </div>
                  <h3 className="mb-2">{step.title}</h3>
                  <p className="text-sm text-muted-foreground">{step.description}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
