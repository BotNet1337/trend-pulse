import { ArrowRight } from 'lucide-react';
import { Button } from '@/shared/components/button';
import { SITE } from '@/shared/site/constants';
import { track, EVENT_SIGN_UP_CLICK } from '@/shared/analytics/track';

export function FinalCtaSection() {
  const signupUrl = (SITE as { signupUrl?: string }).signupUrl ?? '/sign-up';

  return (
    <section id="get-started" className="py-20 md:py-24 px-6 lg:px-20 scroll-mt-16">
      <div className="max-w-4xl mx-auto">
        <div className="fs-glass fs-panel-glow relative overflow-hidden p-10 md:p-14 text-center">
          <div className="relative z-10">
            <h2 className="text-3xl md:text-4xl font-bold mb-4">
              Ready to catch viral trends <span className="fs-grad-text">before everyone else?</span>
            </h2>
            <p className="text-lg text-muted-foreground mb-8 max-w-xl mx-auto">
              Join {SITE.brandName} early access and start receiving viral alerts from public Telegram channels —
              free, no credit card required.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-3.5">
              <Button size="lg" asChild>
                <a href={signupUrl} onClick={() => track(EVENT_SIGN_UP_CLICK)}>
                  {SITE.ctaText} <ArrowRight className="h-4 w-4" />
                </a>
              </Button>
              <Button size="lg" variant="outline" asChild>
                <a href="#pricing">See plans</a>
              </Button>
            </div>
            <p className="text-sm text-[color:var(--aurora-text-faint)] mt-6">
              Free plan · Crypto payments · Public channels only · Raw content not stored &gt;48 h
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
