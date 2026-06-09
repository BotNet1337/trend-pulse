import { Accordion, AccordionItem } from '@/shared/components/accordion';
import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';

export function FaqSection() {
  const brand = SITE.brandName;
  const faqs = [
    {
      question: `What is ${brand}?`,
      answer: `${brand} is a viral-content detector for Telegram. It monitors public channels and alerts you when a topic reaches viral velocity — giving you the earliest possible signal to act on trending news, crypto moves, political events, or anything you track.`,
    },
    {
      question: `Is ${brand} currently available?`,
      answer: `${brand} is in early access. We are actively onboarding users and building out the channel coverage. Sign up for a free account to get started.`,
    },
    {
      question: 'Which Telegram channels does it monitor?',
      answer:
        'Only public channels accessible via @username. Private groups, personal chats, and paid-subscription channels are not accessible and are never monitored.',
    },
    {
      question: 'How long is content stored?',
      answer:
        'Raw message content is automatically discarded within 48 hours of ingestion. Trend signals (score, channel count, timestamp) are retained for the period covered by your plan (Free: none; Pro: 30 days; Team: 90 days).',
    },
    {
      question: 'How does pricing work?',
      answer:
        `${brand} offers three plans: Free ($0 — 5 channels, 1 topic, 5 alerts/day), Pro ($19/mo — 100 channels, 5 topics, unlimited alerts, 30-day history, webhook), and Team ($79/mo — 500 channels, unlimited topics, unlimited alerts, 90-day history, API access). All payments are via cryptocurrency (NOWPayments) — no credit card required.`,
    },
    {
      question: 'Is my data secure and private?',
      answer:
        'We aim for practical security controls. Your account data and alert history are not sold for marketing. Raw Telegram content is never stored beyond 48 hours. Please review our Security and Privacy Policy pages for full details.',
    },
    {
      question: 'Can I connect the alerts to my own systems?',
      answer:
        'Yes. Pro plans include webhook delivery. Team plans include full REST API access so you can pipe viral signals directly into your workflow, dashboard, or automation.',
    },
    {
      question: `Can I use ${brand} for my business?`,
      answer:
        "Yes. The Team plan covers business-scale tracking. If you need a custom channel quota or a custom agreement, contact us and we'll work out the right setup.",
    },
    {
      question: 'Do you offer refunds?',
      answer:
        'Please review our Terms of Service for refund terms. EU consumers have a 14-day statutory withdrawal right.',
    },
    {
      question: 'How can I contact support?',
      answer:
        `Reach us via the contact form on this site or email ${SITE.contactEmail}. Pro and Team customers receive priority support.`,
    },
  ];

  return (
    <section id="faq" className="py-24 px-6 lg:px-20 snap-start scroll-mt-16">
      <div className="max-w-3xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Frequently Asked Questions</h2>
          <p className="text-lg text-muted-foreground">Everything you need to know about {brand}</p>
        </div>

        <Accordion>
          {faqs.map((faq, index) => (
            <AccordionItem key={faq.question} title={faq.question} defaultOpen={index === 0}>
              <p>{faq.answer}</p>
            </AccordionItem>
          ))}
        </Accordion>

        <div className="mt-12 text-center">
          <p className="text-muted-foreground mb-4">Still have questions?</p>
          <Link to="/contact" className="text-primary hover:underline">
            Contact our team →
          </Link>
        </div>
      </div>
    </section>
  );
}
