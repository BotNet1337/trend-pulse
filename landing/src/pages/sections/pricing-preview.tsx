import { Check } from 'lucide-react';
import { Button } from '@/shared/components/button';
import { Badge } from '@/shared/components/badge';
import { SITE } from '@/shared/site/constants';

type PricingPlan = {
  id: string;
  name: string;
  price: number;
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

function formatChannels(n: number): string {
  return n === -1 ? 'Unlimited' : String(n);
}
function formatTopics(n: number): string {
  return n === -1 ? 'Unlimited' : String(n);
}
function formatAlerts(n: number): string {
  return n === -1 ? 'Unlimited' : `${n}/day`;
}
function formatHistory(n: number): string {
  return n === 0 ? 'No history' : `${n} days`;
}

export function PricingPreviewSection() {
  const siteAny = SITE as unknown as { pricing?: { plans?: PricingPlan[]; paymentNote?: string } };
  const plans: PricingPlan[] = siteAny.pricing?.plans ?? [];
  const paymentNote: string =
    siteAny.pricing?.paymentNote ?? 'Payments accepted via cryptocurrency (NOWPayments).';

  const signupUrl = (SITE as { signupUrl?: string }).signupUrl ?? '/sign-up';

  return (
    <section id="pricing" className="py-24 px-6 lg:px-20 bg-muted/20 snap-start scroll-mt-16">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Simple, transparent pricing</h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto mb-4">
            Start free, upgrade when you need more channels or history. All plans include Telegram delivery.
          </p>
          <Badge variant="outline">Crypto payments only · No Stripe · No credit card</Badge>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-8">
          {plans.map((plan) => {
            const isPopular = plan.id === 'pro';
            return (
              <div
                key={plan.id}
                className={[
                  'bg-card border rounded-xl p-8 relative flex flex-col transition-all',
                  isPopular
                    ? 'border-primary shadow-brand scale-105'
                    : 'border-border hover:border-primary/50 hover:shadow-md',
                ].join(' ')}
              >
                {isPopular ? (
                  <Badge className="absolute -top-3 left-1/2 -translate-x-1/2">Most Popular</Badge>
                ) : null}

                <div className="mb-6">
                  <h3 className="text-xl font-bold mb-1">{plan.name}</h3>
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
                  <p className="text-sm text-muted-foreground">{plan.description}</p>
                </div>

                <ul className="space-y-3 mb-8 flex-1">
                  <li className="flex items-start gap-2">
                    <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" aria-hidden="true" />
                    <span className="text-sm">{formatChannels(plan.channels)} channels</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" aria-hidden="true" />
                    <span className="text-sm">{formatTopics(plan.topics)} topic{plan.topics !== 1 ? 's' : ''}</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" aria-hidden="true" />
                    <span className="text-sm">{formatAlerts(plan.alertsPerDay)} alerts</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" aria-hidden="true" />
                    <span className="text-sm">{formatHistory(plan.historyDays)}</span>
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

                <Button
                  className="w-full"
                  variant={isPopular ? 'default' : 'outline'}
                  asChild
                >
                  <a href={signupUrl}>
                    {plan.price === 0 ? 'Start free' : `Get ${plan.name}`}
                  </a>
                </Button>
              </div>
            );
          })}
        </div>

        <p className="text-center text-sm text-muted-foreground">{paymentNote}</p>
      </div>
    </section>
  );
}


