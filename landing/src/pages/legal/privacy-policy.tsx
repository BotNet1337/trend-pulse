import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';
import { LegalPage } from './legal-page';

const PRIVACY_EMAIL = SITE.legal.privacyEmail;
const SUPPORT_EMAIL = SITE.contactEmail;

export function PrivacyPolicyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      lastUpdated={SITE.legal.effectiveDate}
      intro={
        <p>
          {SITE.brandName} respects your privacy and is committed to protecting your personal data. This Privacy Policy
          explains how we collect, use, store, and disclose information about you when you visit our website, create an
          account, or use the {SITE.brandName} service for cross-platform social media publishing (the &quot;Service&quot;).
        </p>
      }
      items={[
        {
          id: 'introduction',
          title: 'Introduction',
          defaultOpen: true,
          content: (
            <>
              <p>
                {SITE.legal.entityName} (&quot;{SITE.brandName}&quot;, &quot;we&quot;, &quot;us&quot;, &quot;our&quot;),
                registered at {SITE.legal.address}, is the data controller for personal data we process about our
                customers and website visitors.
              </p>
              <p>
                For personal data contained in content that you publish to third-party social networks through the
                Service, we act as a <strong>data processor</strong> on your behalf — see our{' '}
                <Link to="/dpa" className="text-primary hover:underline">
                  Data Processing Agreement
                </Link>
                .
              </p>
            </>
          ),
        },
        {
          id: 'information-we-collect',
          title: 'Information We Collect',
          content: (
            <>
              <h3 className="font-semibold text-foreground mb-3">Information You Provide</h3>
              <ul className="space-y-2 mb-4">
                <li>
                  <strong className="text-foreground">Account information:</strong> name, email, hashed password, time
                  zone, language, billing address, and tax identification where required.
                </li>
                <li>
                  <strong className="text-foreground">Billing information:</strong> processed by our payment provider
                  (e.g., Stripe). We store only a tokenised reference and the last four digits of your card.
                </li>
                <li>
                  <strong className="text-foreground">Connected social accounts:</strong> when you connect Instagram,
                  Facebook, YouTube, LinkedIn, X/Twitter, TikTok, Threads, Pinterest, Bluesky, Mastodon, or similar, we
                  receive OAuth access and refresh tokens, the account/page ID, display name, and scopes granted. We do
                  not receive your social-network password.
                </li>
                <li>
                  <strong className="text-foreground">Content you upload:</strong> posts, captions, hashtags, schedules,
                  images, videos, alt text, metadata, drafts, and templates.
                </li>
                <li>
                  <strong className="text-foreground">Support communications:</strong> messages you send through email,
                  contact forms, or support chat, including attachments.
                </li>
              </ul>

              <h3 className="font-semibold text-foreground mb-3 mt-6">Information Collected Automatically</h3>
              <ul className="space-y-2 mb-4">
                <li>
                  <strong className="text-foreground">Usage data:</strong> pages viewed, features used, publishing
                  outcomes, errors, click events, referrers, and session duration.
                </li>
                <li>
                  <strong className="text-foreground">Device and connection data:</strong> IP address, browser type,
                  operating system, device type, screen size, and language preference.
                </li>
                <li>
                  <strong className="text-foreground">Cookies and similar technologies:</strong> see our{' '}
                  <Link to="/cookie-policy" className="text-primary hover:underline">
                    Cookie Policy
                  </Link>
                  .
                </li>
              </ul>

              <h3 className="font-semibold text-foreground mb-3 mt-6">Information from Third Parties</h3>
              <ul className="space-y-2">
                <li>
                  <strong className="text-foreground">Social platform metadata:</strong> post IDs, permalinks, publishing
                  status, error codes, and high-level analytics returned by the platforms you publish to.
                </li>
                <li>
                  <strong className="text-foreground">Payment provider:</strong> Stripe sends us subscription status,
                  invoices, refunds, and fraud signals.
                </li>
                <li>
                  <strong className="text-foreground">Authentication providers:</strong> if you sign in with Google,
                  Apple, or another OAuth provider, we receive your email, name, and provider user ID.
                </li>
              </ul>
            </>
          ),
        },
        {
          id: 'how-we-use',
          title: 'How We Use Information',
          content: (
            <>
              <p className="mb-3">We process personal data under the following GDPR Art. 6 legal bases:</p>
              <ul className="space-y-2">
                <li>
                  <strong className="text-foreground">Performance of a contract:</strong> providing the Service
                  (account, scheduling, publishing, analytics, billing), and customer support.
                </li>
                <li>
                  <strong className="text-foreground">Legitimate interests:</strong> security, fraud and abuse
                  prevention, audit logs, product analytics, and debugging.
                </li>
                <li>
                  <strong className="text-foreground">Consent / legitimate interests:</strong> marketing emails about
                  new features (unsubscribe at any time), depending on jurisdiction.
                </li>
                <li>
                  <strong className="text-foreground">Legal obligation:</strong> tax, accounting, and lawful requests.
                </li>
              </ul>
              <div className="bg-muted/50 p-4 rounded border border-border mt-4">
                <p className="text-sm">
                  <strong>Important:</strong> we do not sell your personal data. We do not use the content you publish
                  to train machine-learning models. We do not read your content for advertising purposes.
                </p>
              </div>
            </>
          ),
        },
        {
          id: 'data-sharing',
          title: 'How We Share Information',
          content: (
            <>
              <p className="mb-3">We share personal data only with the following categories of recipients:</p>
              <ul className="space-y-2">
                <li>
                  <strong className="text-foreground">Social platforms you connect.</strong> When you publish a post,
                  we transmit the content and scheduling parameters to the platform you selected.
                </li>
                <li>
                  <strong className="text-foreground">Subprocessors and infrastructure providers.</strong> Cloud
                  hosting, databases, object storage, email delivery, error monitoring, analytics, support tooling —
                  listed in Schedule 2 of our{' '}
                  <Link to="/dpa" className="text-primary hover:underline">
                    DPA
                  </Link>
                  .
                </li>
                <li>
                  <strong className="text-foreground">Payment processor.</strong> Stripe (or equivalent) for billing
                  and tax calculation.
                </li>
                <li>
                  <strong className="text-foreground">Professional advisers.</strong> Lawyers, accountants, auditors,
                  and insurers under confidentiality obligations.
                </li>
                <li>
                  <strong className="text-foreground">Authorities.</strong> Where required by law, court order, or to
                  protect our rights, safety, or property.
                </li>
                <li>
                  <strong className="text-foreground">Successors.</strong> In a merger, acquisition, or asset sale,
                  personal data may transfer to the successor entity.
                </li>
              </ul>
              <p className="mt-4">We do not sell your personal information to third parties.</p>
            </>
          ),
        },
        {
          id: 'international',
          title: 'International Data Transfers',
          content: (
            <>
              <p className="mb-3">
                We are based in {SITE.legal.jurisdiction} and use infrastructure providers located in the European
                Union and the United States. Where personal data is transferred outside its country of origin, we rely
                on:
              </p>
              <ul className="space-y-2">
                <li>the European Commission&apos;s Standard Contractual Clauses (SCCs) and the UK Addendum,</li>
                <li>adequacy decisions where applicable,</li>
                <li>supplementary technical measures (encryption in transit and at rest).</li>
              </ul>
              <p className="mt-4">
                You can request a copy of the safeguards by emailing{' '}
                <a href={`mailto:${PRIVACY_EMAIL}`} className="text-primary hover:underline">
                  {PRIVACY_EMAIL}
                </a>
                .
              </p>
            </>
          ),
        },
        {
          id: 'data-retention',
          title: 'Data Retention',
          content: (
            <>
              <p className="mb-3">We retain personal data only as long as necessary:</p>
              <ul className="space-y-2">
                <li>
                  <strong className="text-foreground">Account record:</strong> lifetime of your account plus 30 days.
                </li>
                <li>
                  <strong className="text-foreground">Drafts and scheduled posts:</strong> until you delete them or
                  close the account.
                </li>
                <li>
                  <strong className="text-foreground">Connected social-account tokens:</strong> until you disconnect or
                  close {SITE.brandName}.
                </li>
                <li>
                  <strong className="text-foreground">Billing records and invoices:</strong> 7 years (Ukrainian tax
                  law).
                </li>
                <li>
                  <strong className="text-foreground">Server and security logs:</strong> up to 12 months.
                </li>
                <li>
                  <strong className="text-foreground">Backups:</strong> up to 35 days from creation.
                </li>
              </ul>
              <p className="mt-4">
                When you delete your account, we permanently delete or irreversibly anonymise your personal data within
                30 days, except where retention is required by law.
              </p>
            </>
          ),
        },
        {
          id: 'your-rights',
          title: 'Your Rights',
          content: (
            <>
              <p className="mb-3">
                Depending on your jurisdiction (GDPR, UK GDPR, CCPA/CPRA, Ukrainian Law on Personal Data Protection,
                and similar regimes), you have the right to access, rectify, erase, restrict, object, port your data,
                and withdraw consent. You may also lodge a complaint with your local supervisory authority.
              </p>
              <p className="mt-4">
                To exercise these rights, email{' '}
                <a href={`mailto:${PRIVACY_EMAIL}`} className="text-primary hover:underline">
                  {PRIVACY_EMAIL}
                </a>
                . We respond within 30 days and may need to verify your identity.
              </p>
              <p className="mt-4">
                California residents have additional rights — see{' '}
                <Link to="/do-not-sell-or-share" className="text-primary hover:underline">
                  Do Not Sell or Share My Personal Information
                </Link>
                .
              </p>
            </>
          ),
        },
        {
          id: 'security',
          title: 'Security',
          content: (
            <>
              <p className="mb-3">
                We implement administrative, technical, and physical safeguards including encryption in transit (TLS
                1.2+) and at rest (AES-256), access controls, audit logging, and regular backups. See{' '}
                <Link to="/security" className="text-primary hover:underline">
                  Security &amp; Compliance
                </Link>{' '}
                for details.
              </p>
              <p>
                If we become aware of a personal-data breach affecting your information, we will notify you and the
                relevant supervisory authority within 72 hours where required by law.
              </p>
            </>
          ),
        },
        {
          id: 'children',
          title: "Children's Privacy",
          content: (
            <p>
              {SITE.brandName} is not directed to children under 16. We do not knowingly collect personal data from
              children under 16. If you believe a child has provided us with personal data, contact{' '}
              <a href={`mailto:${PRIVACY_EMAIL}`} className="text-primary hover:underline">
                {PRIVACY_EMAIL}
              </a>{' '}
              and we will delete it.
            </p>
          ),
        },
        {
          id: 'third-party',
          title: 'Third-Party Social Networks',
          content: (
            <p>
              Once your content is published to a third-party platform, that platform&apos;s terms and privacy
              policies govern how the content and any resulting interactions are processed. We recommend reviewing the
              privacy policies of every platform you connect.
            </p>
          ),
        },
        {
          id: 'changes',
          title: 'Changes to This Policy',
          content: (
            <p>
              We may update this Privacy Policy from time to time. We will post the revised version on this page,
              update the &quot;Last updated&quot; date, and for material changes notify you by email or in-app notice at
              least 14 days before they take effect.
            </p>
          ),
        },
        {
          id: 'contact',
          title: 'Contact Us',
          content: (
            <ul className="space-y-2">
              <li>
                <strong className="text-foreground">Controller:</strong> {SITE.legal.entityName}
              </li>
              <li>
                <strong className="text-foreground">Address:</strong> {SITE.legal.address}
              </li>
              <li>
                <strong className="text-foreground">Privacy contact:</strong>{' '}
                <a href={`mailto:${PRIVACY_EMAIL}`} className="text-primary hover:underline">
                  {PRIVACY_EMAIL}
                </a>
              </li>
              <li>
                <strong className="text-foreground">General support:</strong>{' '}
                <a href={`mailto:${SUPPORT_EMAIL}`} className="text-primary hover:underline">
                  {SUPPORT_EMAIL}
                </a>
              </li>
            </ul>
          ),
        },
      ]}
    />
  );
}
