import { SITE } from '@/shared/site/constants';

export function HowItWorksSection() {
  const steps = [
    {
      title: 'Pick your topics & channels',
      description:
        'Choose the public Telegram channels you want to track and define the topics that matter to you — crypto, politics, tech, or anything else.',
    },
    {
      title: 'We watch continuously',
      description:
        `${SITE.brandName} continuously scans public channels for emerging patterns, measuring velocity and spread across your channel list in real time.`,
    },
    {
      title: 'Get alerted instantly',
      description:
        'When a topic crosses the viral threshold, you receive an alert with score, channel count, and timestamp — via Telegram or webhook.',
    },
  ];

  return (
    <section id="how-it-works" className="py-20 md:py-24 px-6 lg:px-20 snap-start scroll-mt-16">
      <div className="max-w-6xl mx-auto">
        <div className="text-center max-w-2xl mx-auto mb-12">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">How it works</h2>
          <p className="text-lg text-muted-foreground">
            Get started with {SITE.brandName} in three simple steps
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {steps.map((step, index) => (
            <article key={step.title} className="fs-glass fs-card-hover p-7">
              <span
                className="fs-step-num mb-4 inline-flex h-11 w-11 items-center justify-center rounded-[14px] text-lg font-extrabold"
                aria-hidden="true"
              >
                {index + 1}
              </span>
              <h3 className="mb-1.5 text-lg font-bold">{step.title}</h3>
              <p className="text-sm text-muted-foreground">{step.description}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
