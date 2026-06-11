import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';
import { BLOG_ARTICLES } from '@/shared/blog/articles';
import { BlogArticleLayout } from './blog-article-layout';

const meta = BLOG_ARTICLES.find((a) => a.slug === 'crypto-payments-for-saas-guide');

type PricingPlan = (typeof SITE.pricing.plans)[number];

function planByName(name: string): PricingPlan | undefined {
  return SITE.pricing.plans.find((p) => p.name === name);
}

function formatUsd(amount: number | undefined): string {
  return typeof amount === 'number' ? `$${amount}` : '—';
}

/**
 * TASK-073, article 3 (crypto payments guide — removes friction for the
 * crypto-native audience). All plan prices are interpolated from config.json
 * (lesson task-017: pricing copy is derivative, never a second source of truth).
 * Refund facts mirror the live /refund-policy page (TASK-071).
 */
export function CryptoPaymentsForSaasGuidePage() {
  if (!meta) return null;
  const pro = planByName('Pro');
  const trader = planByName('Trader');

  return (
    <BlogArticleLayout meta={meta}>
      <p>
        {SITE.brandName} is paid in cryptocurrency only — there is no card checkout. If you live in
        crypto this is one less form to fill in; if you have never paid for a subscription with
        crypto before, this guide walks through the whole flow in five steps, including the
        pitfalls that actually cost people money.
      </p>

      <h2>Why crypto payments</h2>
      <p>
        Crypto checkout works the same everywhere in the world, settles in minutes, and does not
        require sharing card details with yet another service. Payments are processed through{' '}
        <strong>{SITE.pricing.paymentProcessor}</strong>, a hosted crypto payment processor: you
        get an invoice with an exact amount and address, pay it from any wallet, and the
        subscription activates once the network confirms the transaction.
      </p>

      <h2>Step 1 — pick a plan</h2>
      <p>
        Current plans (always check the{' '}
        <Link to="/pricing" className="text-primary hover:underline">
          pricing page
        </Link>{' '}
        for the live numbers): <strong>{pro?.name}</strong> at {formatUsd(pro?.price)}/month, with
        quarterly ({formatUsd(pro?.quarterlyPrice)}) and yearly ({formatUsd(pro?.yearlyPrice)})
        prepay options, and <strong>{trader?.name}</strong> at {formatUsd(trader?.price)}/month
        ({formatUsd(trader?.quarterlyPrice)} quarterly, {formatUsd(trader?.yearlyPrice)} yearly).
        Quarterly and yearly invoices are a single upfront payment for the whole period and work
        out cheaper than paying monthly. There is also a free plan — no payment involved at all.
      </p>

      <h2>Step 2 — get an invoice</h2>
      <p>
        Choose the plan and billing period in the app. You get a {SITE.pricing.paymentProcessor}{' '}
        invoice: the USD price converted into the coin you select, a payment address, and the exact
        amount to send. The invoice is valid for a limited time because crypto exchange rates move
        — if it expires, just generate a fresh one.
      </p>

      <h2>Step 3 — choose a coin and network</h2>
      <p>
        {SITE.pricing.paymentProcessor} supports a wide range of coins and networks — stablecoins
        like USDT and USDC are the most predictable choice because the invoice amount does not
        drift while you pay. Two rules prevent nearly all payment problems:
      </p>
      <ul>
        <li>
          <strong>Match the network exactly.</strong> If the invoice says USDT on one network,
          sending USDT on a different network will not be credited automatically.
        </li>
        <li>
          <strong>Account for fees.</strong> The invoice amount is what must <em>arrive</em>.
          Wallets usually handle this; exchanges often deduct a withdrawal fee from the amount you
          enter — add the fee on top, or the payment lands short.
        </li>
      </ul>

      <h2>Step 4 — send and wait for confirmation</h2>
      <p>
        Send the exact amount to the invoice address. Confirmation takes from under a minute to
        tens of minutes depending on the network. Once the processor confirms the payment, the
        plan activates on your account automatically. If you sent slightly less than the invoice
        amount (the classic exchange-fee mistake), the invoice shows a partially-paid state —
        contact{' '}
        <a href={`mailto:${SITE.contactEmail}`} className="text-primary hover:underline">
          {SITE.contactEmail}
        </a>{' '}
        and we will sort it out.
      </p>

      <h2>Step 5 — know how refunds work</h2>
      <p>
        Crypto transactions have no chargebacks, so the refund policy matters more than usual.
        Your <strong>first payment is covered by a 7-day money-back guarantee</strong>: ask within
        7 days and it is refunded in full, manually, in USDT — the USD value of your invoice. The
        full rules, including how to file a request, are on the{' '}
        <Link to="/refund-policy" className="text-primary hover:underline">
          refund policy page
        </Link>
        . We will never ask for your seed phrase or private keys — a refund only needs a USDT
        address to send funds to.
      </p>

      <h2>Quick checklist</h2>
      <ol>
        <li>Pick a plan and billing period (stablecoins make the payment painless).</li>
        <li>Generate the invoice and keep it open.</li>
        <li>Match coin and network exactly; add exchange withdrawal fees on top.</li>
        <li>Send, wait for network confirmation, watch the plan activate.</li>
        <li>Remember: 7-day money-back on the first payment, refunded in USDT.</li>
      </ol>
    </BlogArticleLayout>
  );
}
