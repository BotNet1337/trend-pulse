import { Badge } from '@/shared/components/badge';
import { Button } from '@/shared/components/button';
import { Check } from 'lucide-react';
import { SITE } from '@/shared/site/constants';

export function PricingPage() {
  const plans = [
    {
      name: 'Starter',
      price: 'TBD',
      period: '',
      description: 'For individuals exploring early access',
      features: [
        'Multi-platform publishing (early access scope)',
        'Scheduling & content calendar',
        'Core product access (early access)',
        'Email support',
      ],
      cta: 'Join the waitlist',
      popular: false,
    },
    {
      name: 'Pro',
      price: 'TBD',
      period: '',
      description: 'For power users and small teams (planned)',
      features: [
        'Everything in Starter',
        'Priority onboarding (planned)',
        'API access (planned)',
        'Team features (planned)',
      ],
      cta: 'Join the waitlist',
      popular: true,
    },
    {
      name: 'Enterprise',
      price: 'Custom',
      period: '',
      description: 'For organizations with specific needs (planned)',
      features: [
        'Custom agreement (planned)',
        'Security review (planned)',
        'Dedicated support (planned)',
      ],
      cta: 'Contact sales',
      popular: false,
    },
  ];

  return (
    <div className="pt-24 pb-16">
      <section className="py-16 px-6 lg:px-20">
        <div className="max-w-6xl mx-auto text-center">
          <Badge variant="secondary" className="mb-6">
            Early Access Pricing
          </Badge>
          <h1 className="text-4xl md:text-5xl font-bold mb-6">Choose Your Plan</h1>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto mb-8">
            {SITE.brandName} is in early access—plans and exact terms are still taking shape and can change as we ship
            publishing features.
          </p>
        </div>
      </section>

      <section className="px-6 lg:px-20 pb-16">
        <div className="max-w-6xl mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-16">
            {plans.map((plan) => (
              <div
                key={plan.name}
                className={[
                  'bg-card border rounded-lg p-8 relative transition-all',
                  plan.popular
                    ? 'border-primary shadow-lg scale-105'
                    : 'border-border hover:border-primary/50 hover:shadow-md hover:-translate-y-0.5',
                ].join(' ')}
              >
                {plan.popular ? (
                  <Badge className="absolute -top-3 left-1/2 -translate-x-1/2">Most Popular</Badge>
                ) : null}

                <div className="mb-6">
                  <h2 className="mb-2">{plan.name}</h2>
                  <div className="flex items-baseline gap-1 mb-2">
                    <span className="text-4xl font-bold">{plan.price}</span>
                    <span className="text-muted-foreground">{plan.period}</span>
                  </div>
                  <p className="text-sm text-muted-foreground">{plan.description}</p>
                </div>

                <ul className="space-y-3 mb-8">
                  {plan.features.map((feature) => (
                    <li key={feature} className="flex items-start gap-2">
                      <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" />
                      <span className="text-sm">{feature}</span>
                    </li>
                  ))}
                </ul>

                <Button className="w-full" variant={plan.popular ? 'default' : 'outline'} asChild>
                  <a href={plan.cta === 'Contact sales' ? '/contact' : '/contact'}>{plan.cta}</a>
                </Button>
              </div>
            ))}
          </div>

          <div className="bg-muted/50 border border-border rounded-lg p-6 mb-16">
            <h3 className="mb-2">Pricing Transparency</h3>
            <p className="text-sm text-muted-foreground mb-4">
              {SITE.brandName} is currently in development. Pricing and packaging can change as we add features and refine the
              product.
            </p>
            <p className="text-sm text-muted-foreground">
              We’ll publish concrete terms when paid plans are introduced.
            </p>
          </div>

        </div>
      </section>

      <section className="py-16 px-6 lg:px-20 bg-muted/20">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-3xl font-bold mb-8 text-center">Pricing FAQ</h2>
          <div className="space-y-6">
            <div className="border border-transparent rounded-lg p-4 transition-colors hover:border-foreground/30">
              <h3 className="mb-2">How does pricing work?</h3>
              <p className="text-sm text-muted-foreground">
                Pricing is evolving during early access. We’ll publish concrete plans and terms as the product stabilizes.
              </p>
            </div>
            <div>
              <h3 className="mb-2">Can I change plans?</h3>
              <p className="text-sm text-muted-foreground">
                Once plans are introduced, you’ll be able to change plans based on the published terms.
              </p>
            </div>
            <div>
              <h3 className="mb-2">Do you offer refunds?</h3>
              <p className="text-sm text-muted-foreground">
                Please review our Refund Policy. If paid plans are introduced, it will be updated with concrete terms.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}


