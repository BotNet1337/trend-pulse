import { Badge } from '@/shared/components/badge';
import { Lightbulb, Rocket, Target, Users } from 'lucide-react';
import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';

export function AboutPage() {
  const values = [
    {
      icon: Target,
      title: 'Speed',
      description: 'Viral content waits for no one. We optimize every step so you get the alert before everyone else.',
    },
    {
      icon: Users,
      title: 'User-Centric',
      description: 'Our early access users shape the product. We listen, iterate, and build what you actually need.',
    },
    {
      icon: Lightbulb,
      title: 'Transparency',
      description: 'No vague promises. Clear pricing, honest compliance (public channels only, 48-hour retention), open communication.',
    },
    {
      icon: Rocket,
      title: 'Privacy First',
      description: 'We monitor only public channels. Raw content is discarded within 48 hours. Your data is never sold.',
    },
  ];

  const roadmap = [
    {
      quarter: 'Now',
      status: 'In Progress',
      items: ['Real-time viral detection (public channels)', 'Telegram alert delivery', 'Early access onboarding'],
    },
    {
      quarter: 'Next (M1)',
      status: 'Planned',
      items: ['Webhook delivery (Pro)', 'Multi-topic tracking', 'Alert history UI'],
    },
    {
      quarter: 'Then (M2)',
      status: 'Planned',
      items: ['REST API (Team)', 'Channel group management', 'Trend history dashboard'],
    },
    {
      quarter: 'Later (M3)',
      status: 'Planned',
      items: ['Advanced scoring models', 'Cross-topic correlation', 'Custom alert thresholds'],
    },
  ];

  return (
    <div className="pt-24 pb-16">
      <section className="py-16 px-6 lg:px-20">
        <div className="max-w-4xl mx-auto text-center">
          <p className="fs-eyebrow justify-center mb-4">About {SITE.brandName}</p>
          <h1 className="text-4xl md:text-5xl font-extrabold tracking-[-0.03em] mb-6">
            Your personal <span className="fs-grad-text">viral radar</span> for Telegram
          </h1>
          <p className="text-lg text-muted-foreground mb-8">
            We&apos;re building the fastest way to detect viral content in public Telegram channels. {SITE.brandName}{' '}
            monitors public channels continuously and alerts you the moment a topic crosses the viral threshold.
          </p>
        </div>
      </section>

      <section className="py-16 px-6 lg:px-20">
        <div className="max-w-6xl mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
            <div>
              <h2 className="text-3xl font-bold mb-4">Our Mission</h2>
              <p className="text-muted-foreground mb-4">
                Telegram is one of the world&apos;s fastest-moving information channels. Crypto moves, breaking news, and
                political shifts often surface in public Telegram channels hours before anywhere else. But watching dozens
                of channels manually is impossible.
              </p>
              <p className="text-muted-foreground">
                {SITE.brandName} solves this: we watch public channels for you and surface the signal when it matters.
              </p>
            </div>
            <div className="fs-glass p-8">
              <h3 className="mb-4 text-lg font-bold">Why We&apos;re Building This</h3>
              <ul className="space-y-3">
                <li className="flex items-start gap-2">
                  <div className="w-1.5 h-1.5 bg-primary rounded-full mt-2 shrink-0" />
                  <span className="text-sm text-muted-foreground">
                    Give you the earliest possible viral signal from public Telegram channels
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <div className="w-1.5 h-1.5 bg-primary rounded-full mt-2 shrink-0" />
                  <span className="text-sm text-muted-foreground">
                    Be honest about what we monitor (public channels only) and how long we store it (48-hour raw content limit)
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <div className="w-1.5 h-1.5 bg-primary rounded-full mt-2 shrink-0" />
                  <span className="text-sm text-muted-foreground">
                    Offer transparent pricing with no Stripe, no credit card requirements
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <div className="w-1.5 h-1.5 bg-primary rounded-full mt-2 shrink-0" />
                  <span className="text-sm text-muted-foreground">Maintain strong privacy and security baselines from day one</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      <section className="py-16 px-6 lg:px-20">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-3xl font-bold mb-12 text-center">Our Values</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
            {values.map((value) => {
              const Icon = value.icon;
              return (
                <div key={value.title} className="text-center">
                  <span className="fs-feature-icon mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl">
                    <Icon className="h-7 w-7" />
                  </span>
                  <h3 className="mb-2 text-lg font-bold">{value.title}</h3>
                  <p className="text-sm text-muted-foreground">{value.description}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <section className="py-16 px-6 lg:px-20">
        <div className="max-w-4xl mx-auto text-center">
          <h2 className="text-3xl font-bold mb-6">Built by a Small Team</h2>
          <p className="text-lg text-muted-foreground mb-8">
            {SITE.brandName} is built and maintained by a small team focused on real-time Telegram trend detection.
            We&apos;re in active development and growing carefully.
          </p>
          <p className="text-muted-foreground">
            Interested in joining us?{' '}
            <Link to="/contact" className="text-primary hover:underline">
              Get in touch
            </Link>
          </p>
        </div>
      </section>

      <section className="py-16 px-6 lg:px-20">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold mb-4">Product Roadmap</h2>
            <p className="text-lg text-muted-foreground">
              Here&apos;s what we&apos;ve built and what&apos;s coming next. Dates are estimates and may change.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {roadmap.map((phase) => (
              <div key={phase.quarter} className="fs-glass fs-card-hover p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-base font-bold">{phase.quarter}</h3>
                  <Badge variant={phase.status === 'Completed' ? 'default' : phase.status === 'In Progress' ? 'secondary' : 'outline'}>
                    {phase.status}
                  </Badge>
                </div>
                <ul className="space-y-2">
                  {phase.items.map((item) => (
                    <li key={item} className="flex items-start gap-2 text-sm text-muted-foreground">
                      <div className="w-1.5 h-1.5 bg-primary rounded-full mt-1.5 shrink-0" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="mt-8 text-center">
            <p className="text-sm text-muted-foreground">
              Have a feature request? Early access users can influence our roadmap.{' '}
              <Link to="/contact" className="text-primary hover:underline">
                Share your ideas
              </Link>
            </p>
          </div>
        </div>
      </section>

      <section className="py-16 px-6 lg:px-20">
        <div className="max-w-4xl mx-auto">
          <div className="fs-glass fs-panel-glow relative overflow-hidden p-10 text-center">
            <div className="relative z-10">
              <h3 className="mb-4 text-2xl font-bold">Join Us in Early Access</h3>
              <p className="text-muted-foreground mb-6">
                By joining now, you&apos;ll get early access to viral Telegram alerts, help shape the product roadmap, and
                be among the first to ride waves before everyone else.
              </p>
              <Link to="/" hash="get-started" className="text-primary hover:underline font-medium">
                Get started today →
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
