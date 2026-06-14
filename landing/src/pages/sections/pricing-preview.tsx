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
    <section id="pricing" className="py-20 md:py-24 px-6 lg:px-20 snap-start scroll-mt-16">
      <div className="max-w-6xl mx-auto">
        <div className="text-center max-w-2xl mx-auto mb-12">
          <p className="fs-eyebrow justify-center mb-4">Pricing</p>
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Simple, transparent pricing</h2>
          <p className="text-lg text-muted-foreground mb-5">
            Start free, upgrade when you need more channels or history. All plans include Telegram delivery.
          </p>
          <Badge variant="outline">Crypto payments only · No Stripe · No credit card</Badge>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-stretch mb-8">
          {plans.map((plan) => {
            const isPopular = plan.id === 'pro';
            return (
              <article
                key={plan.id}
                className={[
                  'fs-glass relative flex flex-col p-8 transition-transform duration-200 hover:-translate-y-1',
                  isPopular ? 'fs-plan-featured md:scale-[1.03] hover:md:scale-[1.03]' : '',
                ].join(' ')}
              >
                {isPopular ? (
                  <span className="fs-popular-badge absolute -top-3.5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full px-3.5 py-1.5 text-[0.72rem] font-bold uppercase tracking-[0.08em]">
                    Most Popular
                  </span>
                ) : null}

                <div className="mb-6">
                  <h3 className="text-xl font-bold mb-1">{plan.name}</h3>
                  <div className="flex items-baseline gap-1 mb-2">
                    {plan.price === 0 ? (
                      <span className="text-[2.6rem] font-extrabold leading-none tracking-[-0.03em]">Free</span>
                    ) : (
                      <>
                        <span className="text-[2.6rem] font-extrabold leading-none tracking-[-0.03em] tabular-nums">${plan.price}</span>
                        <span className="text-muted-foreground">/{plan.period}</span>
                      </>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground">{plan.description}</p>
                </div>

                <ul className="space-y-3 mb-8 flex-1">
                  <li className="flex items-start gap-2">
                    <Check className="h-5 w-5 text-[color:var(--aurora-cyan)] shrink-0 mt-0.5" aria-hidden="true" />
                    <span className="text-sm">{formatChannels(plan.channels)} channels</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="h-5 w-5 text-[color:var(--aurora-cyan)] shrink-0 mt-0.5" aria-hidden="true" />
                    <span className="text-sm">{formatTopics(plan.topics)} topic{plan.topics !== 1 ? 's' : ''}</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="h-5 w-5 text-[color:var(--aurora-cyan)] shrink-0 mt-0.5" aria-hidden="true" />
                    <span className="text-sm">{formatAlerts(plan.alertsPerDay)} alerts</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="h-5 w-5 text-[color:var(--aurora-cyan)] shrink-0 mt-0.5" aria-hidden="true" />
                    <span className="text-sm">{formatHistory(plan.historyDays)}</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="h-5 w-5 text-[color:var(--aurora-cyan)] shrink-0 mt-0.5" aria-hidden="true" />
                    <span className="text-sm">Telegram delivery</span>
                  </li>
                  {plan.webhook ? (
                    <li className="flex items-start gap-2">
                      <Check className="h-5 w-5 text-[color:var(--aurora-cyan)] shrink-0 mt-0.5" aria-hidden="true" />
                      <span className="text-sm">Webhook delivery</span>
                    </li>
                  ) : null}
                  {plan.apiAccess ? (
                    <li className="flex items-start gap-2">
                      <Check className="h-5 w-5 text-[color:var(--aurora-cyan)] shrink-0 mt-0.5" aria-hidden="true" />
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
              </article>
            );
          })}
        </div>

        <p className="text-center text-sm text-muted-foreground">{paymentNote}</p>
      </div>
    </section>
  );
}


