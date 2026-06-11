import * as React from 'react';
import { Accordion, AccordionItem } from '@/shared/components/accordion';
import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';

type FaqEntry = {
  question: string;
  answer: React.ReactNode;
};

export function FaqSection() {
  const brand = SITE.brandName;
  const faqs: FaqEntry[] = [
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
        'Raw message content is automatically discarded within 48 hours of ingestion. Trend signals (score, channel count, timestamp) are retained for the period covered by your plan (Free: none; Pro: 30 days; Trader: 90 days).',
    },
    {
      question: 'How does pricing work?',
      answer:
        `${brand} offers three plans: Free ($0 — curated packs + delayed alerts), Pro ($29/mo — 100 channels, 5 topics, unlimited alerts, 30-day history, webhook), and Trader ($99/mo — 500 channels, unlimited topics, unlimited alerts, 90-day history, API access). Prepay quarterly or annually for a discount. All payments are via cryptocurrency (NOWPayments) — no credit card required.`,
    },
    {
      question: "I've never paid with crypto — how does checkout work?",
      answer:
        'It works like any online checkout, just paid from a crypto wallet or exchange instead of a card. Pick a plan, and the NOWPayments checkout shows you a payment address and the exact amount in the coin you choose (USDT and other major coins are supported). Send that amount from any wallet or exchange account, wait for the network confirmation, and your subscription activates automatically. No prior crypto experience needed.',
    },
    {
      question: 'What does the 30-minute delay on the Free plan mean?',
      answer:
        'Free-plan alerts are delivered 30 minutes after our system detects a viral spike. Pro and Trader receive the same alerts in real time. The delay is the trade-off for a $0 plan — if you act on speed (trading, breaking news), real-time alerts are the upgrade that matters.',
    },
    {
      question: 'What are curated channel packs?',
      answer:
        `Curated channel packs are ready-made bundles of public Telegram channels grouped by theme (crypto, news, tech, and more) and maintained by ${brand}. On the Free plan you monitor packs instead of picking individual channels — zero setup. Pro and Trader plans let you track your own channel lists on top of that.`,
    },
    {
      question: 'How do I get an API key?',
      answer:
        'API access is included in the Trader plan. After subscribing, create and manage your API keys from the account settings in your dashboard, then pull viral signals into your own systems via the REST API.',
    },
    {
      question: 'How do I cancel my subscription?',
      answer:
        'Crypto payments are prepaid, so there is no card on file and nothing charges automatically. To cancel, simply do not renew: your plan stays active until the end of the period you paid for, then your account drops to the Free plan. No cancellation form, no retention calls.',
    },
    {
      question: 'Is my data secure and private?',
      answer:
        'We aim for practical security controls. Your account data and alert history are not sold for marketing. Raw Telegram content is never stored beyond 48 hours. Please review our Security and Privacy Policy pages for full details.',
    },
    {
      question: 'Can I connect the alerts to my own systems?',
      answer:
        'Yes. Pro plans include webhook delivery. Trader plans include full REST API access so you can pipe viral signals directly into your workflow, dashboard, or automation.',
    },
    {
      question: `Can I use ${brand} for my business?`,
      answer:
        "Yes. The Trader plan covers business-scale tracking. If you need a custom channel quota or a custom agreement, contact us and we'll work out the right setup.",
    },
    {
      question: 'Do you offer refunds?',
      answer: (
        <>
          Yes — your first payment on any paid plan is covered by a 7-day money-back guarantee, refunded manually in
          USDT. See our{' '}
          <Link to="/refund-policy" className="text-primary hover:underline">
            Refund Policy
          </Link>{' '}
          for the exact procedure. EU consumers also have a 14-day statutory withdrawal right.
        </>
      ),
    },
    {
      question: 'How can I contact support?',
      answer:
        `Reach us via the contact form on this site or email ${SITE.contactEmail}. Pro and Trader customers receive priority support.`,
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
