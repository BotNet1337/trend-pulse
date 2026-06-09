import { SITE } from '@/shared/site/constants';
import { LegalPage } from './legal-page';

const PRIVACY_EMAIL = SITE.legal.privacyEmail;

export function DoNotSellOrSharePage() {
  return (
    <LegalPage
      title="Do Not Sell or Share My Personal Information"
      lastUpdated={SITE.legal.effectiveDate}
      intro={
        <p>
          This page describes the rights of California residents and other US-state residents under the California
          Consumer Privacy Act (&quot;CCPA&quot;), as amended by the California Privacy Rights Act (&quot;CPRA&quot;),
          and similar laws in Virginia, Colorado, Connecticut, Utah, Oregon, Texas, Montana, and others.
        </p>
      }
      items={[
        {
          id: 'no-sale',
          title: 'We Do Not Sell or Share Personal Information',
          defaultOpen: true,
          content: (
            <p>
              {SITE.brandName} <strong>does not sell</strong> personal information for monetary consideration, and we{' '}
              <strong>do not &quot;share&quot;</strong> personal information for cross-context behavioural advertising
              as those terms are defined under the CCPA/CPRA. We have not done so in the past 12 months and we do not
              intend to.
            </p>
          ),
        },
        {
          id: 'what-we-disclose',
          title: 'What We Do Disclose',
          content: (
            <>
              <p className="mb-3">
                To operate the Service, we disclose personal information to service providers and sub-processors who
                are contractually bound to use the data only on our instructions. Categories include:
              </p>
              <ul className="space-y-2">
                <li>
                  <strong className="text-foreground">Cloud infrastructure providers</strong> (e.g., Hetzner,
                  Cloudflare, AWS).
                </li>
                <li>
                  <strong className="text-foreground">Payment processors</strong> (e.g., NOWPayments).
                </li>
                <li>
                  <strong className="text-foreground">Analytics providers</strong> (e.g., Google Analytics 4) — where
                  you have given consent.
                </li>
                <li>
                  <strong className="text-foreground">Customer-support tooling.</strong>
                </li>
                <li>
                  <strong className="text-foreground">Third-party social platforms you connect</strong> — we transmit
                  content you ask us to publish.
                </li>
              </ul>
              <p className="mt-4">
                These disclosures are not &quot;sales&quot; or &quot;shares&quot; under the CCPA/CPRA because the
                recipients are bound by data-protection obligations and do not use the data for their own purposes.
              </p>
            </>
          ),
        },
        {
          id: 'ccpa-rights',
          title: 'Your CCPA / CPRA Rights',
          content: (
            <ul className="space-y-2">
              <li>
                <strong className="text-foreground">Know</strong> what personal information we collect, the sources,
                the purposes, and the categories of recipients.
              </li>
              <li>
                <strong className="text-foreground">Access</strong> a copy of your personal information.
              </li>
              <li>
                <strong className="text-foreground">Delete</strong> your personal information, subject to legal
                exceptions.
              </li>
              <li>
                <strong className="text-foreground">Correct</strong> inaccurate personal information.
              </li>
              <li>
                <strong className="text-foreground">Limit</strong> the use and disclosure of sensitive personal
                information.
              </li>
              <li>
                <strong className="text-foreground">Opt out of sale or sharing</strong> — we do not sell or share, but
                you may submit an opt-out request anyway.
              </li>
              <li>
                <strong className="text-foreground">Non-discrimination</strong> — we will not deny service, charge a
                different price, or provide a different quality of service because you exercised your rights.
              </li>
            </ul>
          ),
        },
        {
          id: 'sensitive-info',
          title: 'Sensitive Personal Information',
          content: (
            <p>
              {SITE.brandName} does not use sensitive personal information for purposes other than those permitted by
              Cal. Civ. Code § 1798.121(a) (e.g., providing the Service, ensuring security and integrity, short-term
              transient use). We therefore do not offer a separate &quot;limit use&quot; link, but you may contact us
              anyway.
            </p>
          ),
        },
        {
          id: 'how-to-exercise',
          title: 'How to Exercise Your Rights',
          content: (
            <>
              <ul className="space-y-2">
                <li>
                  <strong className="text-foreground">Email:</strong>{' '}
                  <a href={`mailto:${PRIVACY_EMAIL}`} className="text-primary hover:underline">
                    {PRIVACY_EMAIL}
                  </a>{' '}
                  with the subject line &quot;California Privacy Rights Request&quot; (or the relevant US state).
                </li>
                <li>
                  <strong className="text-foreground">In-app:</strong> Settings → Privacy → &quot;Manage my data&quot;.
                </li>
                <li>
                  <strong className="text-foreground">Authorised agents:</strong> you may authorise an agent in writing
                  to act on your behalf. We will require proof of authorisation and may also require you to confirm
                  directly.
                </li>
              </ul>
              <p className="mt-4">
                We will verify your identity before fulfilling the request and will respond within 45 days, with a
                possible 45-day extension where reasonably necessary.
              </p>
            </>
          ),
        },
        {
          id: 'gpc',
          title: 'Global Privacy Control',
          content: (
            <p>
              We honour the <strong>Global Privacy Control (GPC)</strong> signal as a valid opt-out request from the
              browser making the request, in line with California Attorney General guidance.
            </p>
          ),
        },
        {
          id: 'other-states',
          title: 'Other US-State Rights',
          content: (
            <p>
              Residents of Virginia (VCDPA), Colorado (CPA), Connecticut (CTDPA), Utah (UCPA), Oregon (OCPA), Texas
              (TDPSA), Montana (MTCDPA), and similar regimes have substantially similar rights. To exercise them,
              contact{' '}
              <a href={`mailto:${PRIVACY_EMAIL}`} className="text-primary hover:underline">
                {PRIVACY_EMAIL}
              </a>
              .
            </p>
          ),
        },
        {
          id: 'financial-incentives',
          title: 'Notice of Financial Incentives',
          content: (
            <p>
              {SITE.brandName} does not currently offer financial incentives in exchange for personal information.
            </p>
          ),
        },
        {
          id: 'contact',
          title: 'Contact',
          content: (
            <p>
              Questions or requests? Email{' '}
              <a href={`mailto:${PRIVACY_EMAIL}`} className="text-primary hover:underline">
                {PRIVACY_EMAIL}
              </a>
              .
            </p>
          ),
        },
      ]}
    />
  );
}
