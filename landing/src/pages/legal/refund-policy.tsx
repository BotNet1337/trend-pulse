import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';
import { LegalPage } from './legal-page';

const SUPPORT_EMAIL = SITE.contactEmail;

export function RefundPolicyPage() {
  return (
    <LegalPage
      title="Refund Policy"
      lastUpdated={SITE.legal.effectiveDate}
      intro={
        <p>
          {SITE.brandName} accepts cryptocurrency payments only, and crypto transactions cannot be charged back. This
          Policy explains exactly when and how we refund you anyway. It should be read together with our{' '}
          <Link to="/terms-of-service" className="text-primary hover:underline">
            Terms of Service
          </Link>
          .
        </p>
      }
      items={[
        {
          id: 'guarantee',
          title: '7-Day Money-Back Guarantee',
          defaultOpen: true,
          content: (
            <>
              <p className="mb-3">
                Your <strong>first payment</strong> on any paid plan — monthly, quarterly, or annual — is covered by a{' '}
                <strong>7-day money-back guarantee</strong>. If {SITE.brandName} is not what you expected, request a
                refund within 7 days of the payment date (the date on your invoice) and we will refund you in full, no
                questions asked.
              </p>
              <p>
                The guarantee applies once per customer, to the first payment only. This keeps the guarantee honest:
                it protects people trying {SITE.brandName} for the first time, not repeated sign-up-and-refund cycles.
              </p>
            </>
          ),
        },
        {
          id: 'how-to-request',
          title: 'How to Request a Refund',
          content: (
            <>
              <p className="mb-3">
                Email{' '}
                <a href={`mailto:${SUPPORT_EMAIL}`} className="text-primary hover:underline">
                  {SUPPORT_EMAIL}
                </a>{' '}
                <strong>from the email address on your account</strong> and include:
              </p>
              <ul className="space-y-2">
                <li>the email address you signed up with;</li>
                <li>the invoice ID or the date and amount of the payment;</li>
                <li>
                  the transaction details of your crypto payment (transaction hash and the coin you paid with), if you
                  have them;
                </li>
                <li>the USDT address you want the refund sent to.</li>
              </ul>
              <p className="mt-4">
                We confirm every refund request by email before sending funds. We will never ask for your wallet seed
                phrase or private keys.
              </p>
            </>
          ),
        },
        {
          id: 'refund-method',
          title: 'Refund Method and Timing',
          content: (
            <>
              <p className="mb-3">
                Refunds are processed <strong>manually</strong> and paid in <strong>USDT</strong>. Because crypto
                exchange rates move between payment and refund, we refund the{' '}
                <strong>USD value of your invoice</strong> (the amount you were billed, in USDT equivalent at the time
                of the refund) — not the exact coins you sent.
              </p>
              <p>
                We process refunds within <strong>10 business days</strong> of confirming your request. Network
                transaction fees for sending the refund are covered by us.
              </p>
            </>
          ),
        },
        {
          id: 'renewals',
          title: 'Renewals and Later Payments',
          content: (
            <p>
              Payments after your first one — renewals, plan upgrades, or a second subscription — are reviewed{' '}
              <strong>case-by-case</strong> and are not covered by the money-back guarantee. If something went wrong
              (for example, you renewed by mistake), write to{' '}
              <a href={`mailto:${SUPPORT_EMAIL}`} className="text-primary hover:underline">
                {SUPPORT_EMAIL}
              </a>{' '}
              and we will look at it in good faith, but we cannot promise a refund.
            </p>
          ),
        },
        {
          id: 'eu-rights',
          title: 'EU Consumer Rights',
          content: (
            <p>
              If you are a consumer in the European Union, you have a statutory <strong>14-day right of
              withdrawal</strong> from a paid subscription, unless you asked us to begin providing the Service during
              the withdrawal period and acknowledged the loss of the withdrawal right. Nothing in this Policy limits
              that right or any other right you have under applicable consumer protection law.
            </p>
          ),
        },
        {
          id: 'contact',
          title: 'Contact',
          content: (
            <p>
              Questions about this Policy or a pending refund? Email{' '}
              <a href={`mailto:${SUPPORT_EMAIL}`} className="text-primary hover:underline">
                {SUPPORT_EMAIL}
              </a>
              .
            </p>
          ),
        },
      ]}
    />
  );
}
