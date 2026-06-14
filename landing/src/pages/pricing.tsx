import * as React from 'react';
import { Link } from '@tanstack/react-router';
import { Badge } from '@/shared/components/badge';
import { Button } from '@/shared/components/button';
import { Check } from 'lucide-react';
import { SITE } from '@/shared/site/constants';
import { track, EVENT_PRICING_VIEW } from '@/shared/analytics/track';

type PricingPlan = {
  id: string;
  name: string;
  price: number;
  /** Optional prepaid-period prices (TASK-047). Absent field = line not rendered. */
  quarterlyPrice?: number;
  yearlyPrice?: number;
  period: string;
  channels: number;
  topics: number;
  alertsPerDay: number;
  historyDays: number;
  delivery: string[];
  webhook: boolean;
  apiAccess: boolean;
  description: string;
};

export function PricingPage() {
  const siteAny = SITE as unknown as {
    pricing?: { plans?: PricingPlan[]; paymentNote?: string; annualNote?: string };
    signupUrl?: string;
  };
  const plans: PricingPlan[] = siteAny.pricing?.plans ?? [];
  const paymentNote: string =
    siteAny.pricing?.paymentNote ?? 'Payments accepted via cryptocurrency (NOWPayments). No credit card required.';
  const annualNote = siteAny.pricing?.annualNote;
  const signupUrl = siteAny.signupUrl ?? '/sign-up';

  // TASK-068: pricing_view fires once per page visit (ref guards re-running effects/remounts).
  const pricingViewFired = React.useRef(false);
  React.useEffect(() => {
    if (pricingViewFired.current) return;
    pricingViewFired.current = true;
    track(EVENT_PRICING_VIEW);
  }, []);

  return (
    <div className="pt-24 pb-16">
      <section className="py-16 px-6 lg:px-20">
        <div className="max-w-6xl mx-auto text-center">
          <Badge variant="secondary" className="mb-6">
            Simple Pricing
          </Badge>
          <h1 className="text-aurora-gradient text-4xl md:text-5xl font-bold mb-6">Choose Your Plan</h1>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto mb-4">
            Start free. Upgrade when you need more channels, topics, or history.
            All plans include Telegram alert delivery. Public channels only.
          </p>
          <Badge variant="outline">Crypto payments only · No credit card · No Stripe</Badge>
        </div>
      </section>

      <section className="px-6 lg:px-20 pb-16">
        <div className="max-w-6xl mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-12">
            {plans.map((plan) => {
              const isPopular = plan.id === 'pro';
              // TASK-047: prepaid-period line — render only the fields present in config.
              const periodPrices = [
                plan.quarterlyPrice != null ? `$${plan.quarterlyPrice}/quarter` : null,
                plan.yearlyPrice != null ? `$${plan.yearlyPrice}/year` : null,
              ].filter((line): line is string => line !== null);
              return (
                <div
                  key={plan.id}
                  className={[
                    'bg-card border rounded-xl p-8 relative flex flex-col transition-all',
                    isPopular
                      ? 'border-primary shadow-brand scale-105'
                      : 'border-border hover:border-primary/50 hover:shadow-md hover:-translate-y-0.5',
                  ].join(' ')}
                >
                  {isPopular ? (
                    <Badge className="absolute -top-3 left-1/2 -translate-x-1/2">Most Popular</Badge>
                  ) : null}

                  <div className="mb-6">
                    <h2 className="text-xl font-bold mb-1">{plan.name}</h2>
                    <div className="flex items-baseline gap-1 mb-2">
                      {plan.price === 0 ? (
                        <span className="text-4xl font-bold">Free</span>
                      ) : (
                        <>
                          <span className="text-4xl font-bold">${plan.price}</span>
                          <span className="text-muted-foreground">/{plan.period}</span>
                        </>
                      )}
                    </div>
                    {periodPrices.length > 0 ? (
                      <p className="text-xs text-muted-foreground mb-2">
                        or {periodPrices.join(' · ')}
                      </p>
                    ) : null}
                    <p className="text-sm text-muted-foreground">{plan.description}</p>
                  </div>

                  <ul className="space-y-3 mb-8 flex-1">
                    {plan.channels === 0 ? (
                      <li className="flex items-start gap-2">
                        <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" aria-hidden="true" />
                        <span className="text-sm">Curated channel packs</span>
                      </li>
                    ) : (
                      <li className="flex items-start gap-2">
                        <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" aria-hidden="true" />
                        <span className="text-sm">
                          {plan.channels === -1 ? 'Unlimited' : plan.channels} channels
                        </span>
                      </li>
                    )}
                    <li className="flex items-start gap-2">
                      <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" aria-hidden="true" />
                      <span className="text-sm">
                        {plan.topics === -1 ? 'Unlimited' : plan.topics} topic{plan.topics !== 1 ? 's' : ''}
                      </span>
                    </li>
                    <li className="flex items-start gap-2">
                      <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" aria-hidden="true" />
                      <span className="text-sm">
                        {plan.alertsPerDay === -1 ? 'Unlimited' : `${plan.alertsPerDay}/day`} alerts
                        {plan.channels === 0 ? ' (30 min delay)' : ''}
                      </span>
                    </li>
                    <li className="flex items-start gap-2">
                      <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" aria-hidden="true" />
                      <span className="text-sm">
                        {plan.historyDays === 0 ? 'No trend history' : `${plan.historyDays}-day trend history`}
                      </span>
                    </li>
                    <li className="flex items-start gap-2">
                      <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" aria-hidden="true" />
                      <span className="text-sm">Telegram delivery</span>
                    </li>
                    {plan.webhook ? (
                      <li className="flex items-start gap-2">
                        <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" aria-hidden="true" />
                        <span className="text-sm">Webhook delivery</span>
                      </li>
                    ) : null}
                    {plan.apiAccess ? (
                      <li className="flex items-start gap-2">
                        <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" aria-hidden="true" />
                        <span className="text-sm">API access</span>
                      </li>
                    ) : null}
                  </ul>

                  <Button className="w-full" variant={isPopular ? 'default' : 'outline'} asChild>
                    <a href={signupUrl}>
                      {plan.price === 0 ? 'Start free' : `Get ${plan.name}`}
                    </a>
                  </Button>
                </div>
              );
            })}
          </div>

          <div className="bg-muted/50 border border-border rounded-lg p-6 mb-8 text-center">
            {annualNote ? (
              <p className="text-sm font-medium text-foreground mb-1">{annualNote}</p>
            ) : null}
            <p className="text-sm text-muted-foreground">{paymentNote}</p>
            <p className="text-sm text-muted-foreground mt-1">
              7-day money-back on your first payment — see our{' '}
              <Link to="/refund-policy" className="text-primary hover:underline">
                Refund Policy
              </Link>
              .
            </p>
            <p className="text-sm text-muted-foreground mt-1">
              Raw Telegram content is never stored beyond 48 hours. Only public channels are monitored.
            </p>
          </div>
        </div>
      </section>

      <section className="py-16 px-6 lg:px-20 bg-muted/20">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-3xl font-bold mb-8 text-center">Pricing FAQ</h2>
          <div className="space-y-6">
            <div className="border border-transparent rounded-lg p-4 transition-colors hover:border-foreground/30">
              <h3 className="mb-2">What payment methods are accepted?</h3>
              <p className="text-sm text-muted-foreground">
                Cryptocurrency only via NOWPayments. No credit card, no Stripe.
              </p>
            </div>
            <div>
              <h3 className="mb-2">Can I change plans?</h3>
              <p className="text-sm text-muted-foreground">
                Yes. You can upgrade or downgrade at any time. Changes take effect at the start of the next billing cycle.
              </p>
            </div>
            <div>
              <h3 className="mb-2">Do you offer refunds?</h3>
              <p className="text-sm text-muted-foreground">
                Yes — your first payment is covered by a 7-day money-back guarantee. See our{' '}
                <Link to="/refund-policy" className="text-primary hover:underline">
                  Refund Policy
                </Link>{' '}
                for the full procedure. EU consumers also have a 14-day statutory withdrawal right.
              </p>
            </div>
            <div>
              <h3 className="mb-2">Are private Telegram channels supported?</h3>
              <p className="text-sm text-muted-foreground">
                No. {SITE.brandName} monitors only public channels accessible via @username. Private channels are never accessible.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}


