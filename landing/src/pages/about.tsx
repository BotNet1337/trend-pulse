import { Badge } from '@/shared/components/badge';
import { Lightbulb, Rocket, Target, Users } from 'lucide-react';
import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';

export function AboutPage() {
  const values = [
    {
      icon: Target,
      title: 'Simplicity',
      description: 'Publishing across networks should feel straightforward. We focus on clear flows and fewer dead ends.',
    },
    {
      icon: Users,
      title: 'User-Centric',
      description: 'Our early access users shape the product. We listen, iterate, and build what you actually need.',
    },
    {
      icon: Lightbulb,
      title: 'Innovation',
      description: 'We invest in workflows that save time—smarter scheduling, reuse, and consistency across channels.',
    },
    {
      icon: Rocket,
      title: 'Transparency',
      description: 'No hidden fees, no vague promises. Clear pricing direction, open communication, and honest timelines.',
    },
  ];

  const roadmap = [
    {
      quarter: 'Now',
      status: 'In Progress',
      items: ['Core publish & schedule flows', 'Connected accounts baseline', 'Early access onboarding'],
    },
    {
      quarter: 'Next (M1)',
      status: 'Planned',
      items: ['More platform integrations', 'Media workflows & drafts queue', 'API access (planned)'],
    },
    {
      quarter: 'Then (M2)',
      status: 'Planned',
      items: ['Team collaboration & approvals (planned)', 'Analytics overview (planned)', 'Bulk scheduling (planned)'],
    },
    {
      quarter: 'Later (M3)',
      status: 'Planned',
      items: ['Production hardening + monitoring (planned)', 'Reliability for high-volume posters (planned)', 'UX polish (planned)'],
    },
  ];

  return (
    <div className="pt-24 pb-16">
      <section className="py-16 px-6 lg:px-20">
        <div className="max-w-4xl mx-auto text-center">
          <Badge variant="secondary" className="mb-6">
            About {SITE.brandName}
          </Badge>
          <h1 className="text-4xl md:text-5xl font-bold mb-6">One workspace. Every platform you post to.</h1>
          <p className="text-lg text-muted-foreground mb-8">
            We&apos;re building the fastest way to keep a consistent presence across social networks. {SITE.brandName}{' '}
            brings planning, scheduling, and publishing into one streamlined place.
          </p>
        </div>
      </section>

      <section className="py-16 px-6 lg:px-20 bg-muted/20">
        <div className="max-w-6xl mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
            <div>
              <h2 className="text-3xl font-bold mb-4">Our Mission</h2>
              <p className="text-muted-foreground mb-4">
                Creators and teams juggle native apps, different formats, and loose threads just to ship one campaign. We
                believe there&apos;s a better way to work.
              </p>
              <p className="text-muted-foreground">
                {SITE.brandName} unifies how you prepare and send content—so you can show up everywhere that matters with
                less friction and clearer oversight.
              </p>
            </div>
            <div className="bg-card border border-border rounded-lg p-8">
              <h3 className="mb-4">Why We&apos;re Building This</h3>
              <ul className="space-y-3">
                <li className="flex items-start gap-2">
                  <div className="w-1.5 h-1.5 bg-primary rounded-full mt-2 shrink-0" />
                  <span className="text-sm text-muted-foreground">
                    Cut down tab-hopping between networks when you publish the same story
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <div className="w-1.5 h-1.5 bg-primary rounded-full mt-2 shrink-0" />
                  <span className="text-sm text-muted-foreground">
                    Offer transparent pricing that scales with how you actually use the product
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <div className="w-1.5 h-1.5 bg-primary rounded-full mt-2 shrink-0" />
                  <span className="text-sm text-muted-foreground">
                    Ship features that respect real publishing workflows—not generic &quot;social tools&quot;
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <div className="w-1.5 h-1.5 bg-primary rounded-full mt-2 shrink-0" />
                  <span className="text-sm text-muted-foreground">Maintain strong privacy and security baselines</span>
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
                  <div className="w-16 h-16 bg-primary/10 rounded-full flex items-center justify-center mx-auto mb-4">
                    <Icon className="h-8 w-8 text-primary" />
                  </div>
                  <h3 className="mb-2">{value.title}</h3>
                  <p className="text-sm text-muted-foreground">{value.description}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <section className="py-16 px-6 lg:px-20 bg-muted/20">
        <div className="max-w-4xl mx-auto text-center">
          <h2 className="text-3xl font-bold mb-6">Built by a Small Team</h2>
          <p className="text-lg text-muted-foreground mb-8">
            {SITE.brandName} is built and maintained by a small team that cares about making cross-platform publishing
            easier. We&apos;re in active development and growing carefully.
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
              <div key={phase.quarter} className="bg-card border border-border rounded-lg p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3>{phase.quarter}</h3>
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

      <section className="py-16 px-6 lg:px-20 bg-muted/20">
        <div className="max-w-4xl mx-auto">
          <div className="bg-card border border-primary/50 rounded-lg p-8 text-center">
            <h3 className="mb-4">Join Us in Early Access</h3>
            <p className="text-muted-foreground mb-6">
              By joining now, you&apos;ll get early access pricing, help shape publishing workflows, and be part of building
              a calmer way to post everywhere.
            </p>
            <Link to="/" hash="get-started" className="text-primary hover:underline font-medium">
              Get started today →
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
