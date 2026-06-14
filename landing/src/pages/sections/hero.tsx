import { ArrowRight } from 'lucide-react';
import { Button } from '@/shared/components/button';
import { SITE } from '@/shared/site/constants';
import { track, EVENT_SIGN_UP_CLICK } from '@/shared/analytics/track';

export function HeroSection() {
  const signupUrl = (SITE as { signupUrl?: string }).signupUrl ?? '/sign-up';
  // TASK-067: rendered only when the showcase channel exists (owner fills after TASK-070).
  const showcaseTelegramUrl = (SITE as { showcaseTelegramUrl?: string }).showcaseTelegramUrl ?? '';

  return (
    <section className="relative overflow-hidden pt-28 pb-20 md:pt-32 md:pb-28 px-6 lg:px-20 snap-start scroll-mt-16">
      <div className="max-w-7xl mx-auto">
        <div className="grid items-center gap-14 lg:grid-cols-[1.05fr_1fr] lg:gap-16">
          {/* ── Left: copy ── */}
          <div>
            <p className="inline-flex items-center gap-2 mb-6 rounded-full border border-white/10 bg-white/5 px-3.5 py-1.5 text-sm font-medium text-muted-foreground backdrop-blur-md">
              <span className="fs-dot inline-block h-[7px] w-[7px] rounded-full" aria-hidden="true" />
              Early Access · Public Telegram Channels Only
            </p>

            <h1 className="text-4xl md:text-5xl lg:text-6xl font-extrabold leading-[1.08] tracking-[-0.03em] mb-5">
              Catch viral Telegram content{' '}
              <span className="fs-grad-text">before it explodes</span>
            </h1>

            <p className="text-lg md:text-xl text-muted-foreground mb-8 max-w-xl">
              {SITE.brandName} monitors public Telegram channels and alerts you the moment a topic
              goes viral — so you always ride the wave, not follow it.
            </p>

            <div className="flex flex-wrap items-center gap-3.5 mb-7">
              <Button size="lg" asChild>
                <a href={signupUrl} onClick={() => track(EVENT_SIGN_UP_CLICK)}>
                  {SITE.ctaText} <ArrowRight className="h-4 w-4" />
                </a>
              </Button>
              {showcaseTelegramUrl ? (
                <Button size="lg" variant="outline" asChild>
                  <a href={showcaseTelegramUrl} target="_blank" rel="noopener noreferrer">
                    See live detections
                  </a>
                </Button>
              ) : (
                <Button size="lg" variant="outline" asChild>
                  <a href="#how-it-works">See how it works</a>
                </Button>
              )}
            </div>

            <p className="text-sm text-[color:var(--aurora-text-faint)]">
              No credit card · Crypto payments · Public channels only · Raw content not stored &gt;48 h
            </p>
          </div>

          {/* ── Right: product visualization. Decorative chrome (avatar, sparkline,
               z-score float) is aria-hidden; the alert text matches the original copy. ── */}
          <div
            className="relative mx-auto w-full max-w-[560px] pt-28 sm:pt-0 lg:mx-0"
            role="img"
            aria-label={`Example viral alert from ${SITE.brandName}`}
          >
            {/* Floating: velocity vs baseline (decorative) */}
            <div className="fs-glass fs-float-velocity absolute -right-2 top-0 z-30 w-52 rounded-[20px] p-3.5 text-sm sm:right-0" aria-hidden="true">
              <p className="mb-1 font-medium text-[color:var(--aurora-text-faint)]">Velocity vs baseline</p>
              <p className="fs-grad-text m-0 text-xl font-extrabold tracking-[-0.02em]">+412%</p>
              <svg width="100%" height="36" viewBox="0 0 168 36" fill="none" preserveAspectRatio="none" aria-hidden="true" className="mt-1">
                <defs>
                  <linearGradient id="fs-spark-grad" x1="0" y1="0" x2="168" y2="0" gradientUnits="userSpaceOnUse">
                    <stop offset="0" stopColor="#60a5fa" />
                    <stop offset="1" stopColor="#22d3ee" />
                  </linearGradient>
                </defs>
                <path
                  d="M2 31 L22 29 L42 30 L62 27 L82 28 L102 22 L122 16 L142 8 L166 3"
                  stroke="url(#fs-spark-grad)"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>

            <p className="text-xs text-muted-foreground text-center mb-3 uppercase tracking-widest">
              Example alert
            </p>

            {/* Alert card — original copy, Aurora glass treatment */}
            <div className="fs-alert-card fs-glass relative z-20 p-6 font-mono text-sm">
              <p className="text-foreground leading-relaxed">
                🔥 <strong>Viral alert</strong> [crypto] —{' '}
                <span className="text-[color:var(--aurora-cyan-bright)]">&quot;Bitcoin ETF approval&quot;</span>
              </p>
              <p className="text-muted-foreground mt-1">
                Score: <strong className="text-foreground">94</strong>
                &nbsp;·&nbsp; 47 channels in 23 min
                &nbsp;·&nbsp; first seen 14:02
              </p>
            </div>

            {/* Floating: z-score (decorative) */}
            <div className="fs-glass fs-float-zscore absolute -left-2 -bottom-4 z-30 hidden items-center gap-2.5 rounded-[20px] px-4 py-3 text-sm font-semibold text-muted-foreground sm:flex" aria-hidden="true">
              <span className="text-base font-extrabold text-[color:var(--aurora-violet)]">σ</span>
              <span>z-score 4.2</span>
            </div>

            <p className="text-xs text-muted-foreground text-center mt-4">
              Only public channels monitored. Raw content discarded after 48 h.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
