import { Activity, Bell, Clock, FileCheck, Radio, Webhook } from 'lucide-react';

export function FeaturesSection() {
  const features = [
    {
      icon: Radio,
      title: 'Real-time viral detection',
      description:
        'Continuously scans public Telegram channels and measures topic velocity — you know within minutes when something breaks out.',
    },
    {
      icon: Activity,
      title: 'Viral score & spread',
      description:
        'Every alert includes a viral score, channel count, and time-to-viral — so you can judge signal strength at a glance.',
    },
    {
      icon: Bell,
      title: 'Multi-topic alerts',
      description:
        'Set up multiple topics — crypto, politics, tech, sports — and receive targeted alerts for each one separately.',
    },
    {
      icon: Clock,
      title: '30-day trend history',
      description:
        'Pro and Trader plans retain trend signals for up to 30 or 90 days so you can spot recurring patterns and seasonal spikes.',
    },
    {
      icon: Webhook,
      title: 'Webhook & API delivery',
      description:
        'Pipe viral alerts directly into your stack via webhooks (Pro+) or the full REST API (Team). Automate your entire response workflow.',
    },
    {
      icon: FileCheck,
      title: 'Compliance by design',
      description:
        'Only public channels (@username). Raw content never stored beyond 48 h. Privacy, ToS, and acceptable-use policies documented from day one.',
    },
  ];

  return (
    <section id="features" className="py-24 px-6 lg:px-20 snap-start scroll-mt-16">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Everything you need to catch the wave early</h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            From real-time detection to automated delivery — built for speed, transparency, and privacy.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {features.map((feature) => {
            const Icon = feature.icon;
            return (
              <div key={feature.title} className="group">
                <div className="bg-card border border-border rounded-lg p-6 h-full transition-all hover:shadow-md hover:border-primary/50">
                  <div className="w-12 h-12 bg-primary/10 rounded-lg flex items-center justify-center mb-4 group-hover:bg-primary/20 transition-colors">
                    <Icon className="h-6 w-6 text-primary" aria-hidden="true" />
                  </div>
                  <h3 className="mb-2">{feature.title}</h3>
                  <p className="text-sm text-muted-foreground">{feature.description}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
