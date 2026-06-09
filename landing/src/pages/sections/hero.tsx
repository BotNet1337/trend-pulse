import { ArrowRight } from 'lucide-react';
import { Button } from '@/shared/components/button';
import { Badge } from '@/shared/components/badge';
import { SITE } from '@/shared/site/constants';

export function HeroSection() {
  const signupUrl = (SITE as { signupUrl?: string }).signupUrl ?? '/sign-up';

  return (
    <section className="pt-32 pb-16 px-6 lg:px-20 snap-start scroll-mt-16">
      <div className="max-w-4xl mx-auto text-center">
        <Badge variant="secondary" className="mb-6">
          Early Access · Public Telegram Channels Only
        </Badge>

        <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold mb-6 tracking-tight">
          Catch viral Telegram content<br className="hidden md:block" /> before it explodes
        </h1>

        <p className="text-lg md:text-xl text-muted-foreground mb-8 max-w-2xl mx-auto">
          {SITE.brandName} monitors public Telegram channels and alerts you the moment a topic
          goes viral — so you always ride the wave, not follow it.
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-10">
          <Button size="lg" className="w-full sm:w-auto" asChild>
            <a href={signupUrl}>
              {SITE.ctaText} <ArrowRight className="ml-2 h-4 w-4" />
            </a>
          </Button>
          <Button size="lg" variant="outline" className="w-full sm:w-auto" asChild>
            <a href="#how-it-works">See how it works</a>
          </Button>
        </div>

        <p className="text-sm text-muted-foreground">
          No credit card · Crypto payments · Public channels only · Raw content not stored &gt;48 h
        </p>
      </div>

      {/* Viral-alert example (overview §1) */}
      <div className="max-w-2xl mx-auto mt-16">
        <p className="text-xs text-muted-foreground text-center mb-3 uppercase tracking-widest">
          Example alert
        </p>
        <div
          className="bg-card border border-border rounded-xl p-5 shadow-sm font-mono text-sm"
          role="img"
          aria-label="Example viral alert from TrendPulse"
        >
          <p className="text-foreground leading-relaxed">
            🔥 <strong>Viral alert</strong> [crypto] —{' '}
            <span className="text-primary">&quot;Bitcoin ETF approval&quot;</span>
          </p>
          <p className="text-muted-foreground mt-1">
            Score: <strong className="text-foreground">94</strong>
            &nbsp;·&nbsp; 47 channels in 23 min
            &nbsp;·&nbsp; first seen 14:02
          </p>
        </div>
        <p className="text-xs text-muted-foreground text-center mt-2">
          Only public channels monitored. Raw content discarded after 48 h.
        </p>
      </div>
    </section>
  );
}


