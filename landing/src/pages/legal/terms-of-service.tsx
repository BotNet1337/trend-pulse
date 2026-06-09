import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';
import { LegalPage } from './legal-page';

const SUPPORT_EMAIL = SITE.contactEmail;
const SECURITY_EMAIL = SITE.legal.securityEmail;

export function TermsOfServicePage() {
  return (
    <LegalPage
      title="Terms of Service"
      lastUpdated={SITE.legal.effectiveDate}
      intro={
        <p>
          These Terms of Service form a binding agreement between you and {SITE.legal.entityName} (&quot;
          {SITE.brandName}&quot;, &quot;we&quot;, &quot;us&quot;). They govern your access to and use of the{' '}
          {SITE.brandName} website, applications, APIs, and services (the &quot;Service&quot;).
        </p>
      }
      items={[
        {
          id: 'acceptance',
          title: 'Acceptance of Terms',
          defaultOpen: true,
          content: (
            <p>
              By creating an account, clicking &quot;I agree&quot;, or using the Service, you confirm that you have
              read, understood, and agreed to these Terms, the{' '}
              <Link to="/privacy-policy" className="text-primary hover:underline">
                Privacy Policy
              </Link>
              , and the{' '}
              <Link to="/acceptable-use-policy" className="text-primary hover:underline">
                Acceptable Use Policy
              </Link>
              . If you are using the Service on behalf of an organisation, you represent that you are authorised to
              bind that organisation.
            </p>
          ),
        },
        {
          id: 'service',
          title: 'The Service',
          content: (
            <>
              <p className="mb-3">
                {SITE.brandName} is a software-as-a-service tool that monitors public Telegram channels, detects viral
                content trends, and delivers alerts to your configured delivery channels (Telegram bot, webhook, or API).
                We monitor only public channels (@username); private groups and personal chats are not accessible.
                Raw message content is not stored beyond 48 hours.
              </p>
              <p>
                We do not own, control, or endorse any third-party platform, and we are not responsible for the
                availability, terms, or behaviour of those platforms. Features labelled &quot;beta&quot;,
                &quot;preview&quot;, or &quot;early access&quot; are provided &quot;as is&quot; and may change or be
                removed at any time.
              </p>
            </>
          ),
        },
        {
          id: 'eligibility',
          title: 'Eligibility',
          content: (
            <p>
              You must be at least 16 years old (or the age of digital consent in your jurisdiction) to use the
              Service. By using {SITE.brandName}, you confirm you are not located in a country subject to a
              comprehensive embargo by the Ukrainian government, the EU, or the UN Security Council, and that you are
              not on any sanctions list.
            </p>
          ),
        },
        {
          id: 'accounts',
          title: 'Accounts',
          content: (
            <ul className="space-y-2">
              <li>You are responsible for keeping your credentials confidential and for all activity under your account.</li>
              <li>You must provide accurate, current, and complete information when registering.</li>
              <li>
                You must notify us at{' '}
                <a href={`mailto:${SECURITY_EMAIL}`} className="text-primary hover:underline">
                  {SECURITY_EMAIL}
                </a>{' '}
                of any unauthorised access.
              </li>
              <li>
                We may suspend or terminate accounts that violate these Terms or the{' '}
                <Link to="/acceptable-use-policy" className="text-primary hover:underline">
                  AUP
                </Link>
                .
              </li>
            </ul>
          ),
        },
        {
          id: 'connecting-platforms',
          title: 'Connecting Third-Party Platforms',
          content: (
            <>
              <p className="mb-3">
                When you configure channel tracking in {SITE.brandName}, you represent that the channels you add are
                public and accessible to anyone. You must not attempt to access private groups, personal accounts, or
                paid-subscription channels through the Service.
              </p>
              <p>
                You are solely responsible for how you use the viral-trend data and alerts delivered by the Service,
                and for complying with Telegram&apos;s terms of service, applicable copyright law, and any other
                applicable regulations regarding the content you observe.
              </p>
            </>
          ),
        },
        {
          id: 'customer-content',
          title: 'Your Configuration Data',
          content: (
            <>
              <p className="mb-3">
                &quot;Configuration Data&quot; means the channel lists, topic keywords, alert thresholds, webhook URLs,
                and other settings you provide to configure the Service.
              </p>
              <ul className="space-y-2">
                <li>You retain all ownership of your Configuration Data.</li>
                <li>
                  You grant {SITE.brandName} a worldwide, non-exclusive, royalty-free licence to use your Configuration
                  Data <strong>solely as necessary to operate, secure, and improve the Service</strong>.
                </li>
                <li>
                  You represent that your Configuration Data does not violate any third-party rights or applicable law.
                </li>
              </ul>
            </>
          ),
        },
        {
          id: 'billing',
          title: 'Subscriptions, Fees, and Billing',
          content: (
            <>
              <ul className="space-y-2">
                <li>
                  <strong className="text-foreground">Plans and pricing.</strong> Plans, prices, and features are
                  listed on our website. Prices are stated exclusive of applicable taxes unless otherwise indicated.
                </li>
                <li>
                  <strong className="text-foreground">Auto-renewal.</strong> Paid subscriptions renew automatically.
                  You can cancel at any time from your account settings; cancellation takes effect at the end of the
                  current billing cycle.
                </li>
                <li>
                  <strong className="text-foreground">Refunds.</strong> Except where required by law (including the EU
                  consumer right of withdrawal where applicable), fees are non-refundable.
                </li>
                <li>
                  <strong className="text-foreground">Taxes.</strong> You are responsible for any VAT, sales tax, or
                  GST associated with your purchase.
                </li>
                <li>
                  <strong className="text-foreground">Payment method.</strong> We accept cryptocurrency payments only
                  (via NOWPayments). No credit card or bank transfer is accepted.
                </li>
                <li>
                  <strong className="text-foreground">Failed payments.</strong> If a crypto payment is not confirmed,
                  we may downgrade or suspend your account until payment is resolved.
                </li>
              </ul>
              <div className="bg-muted/50 p-4 rounded border border-border mt-4">
                <p className="text-sm">
                  <strong>EU consumer withdrawal:</strong> if you are an EU consumer, you have 14 days to withdraw
                  from a paid subscription without giving a reason, unless you asked us to begin providing the Service
                  during the withdrawal period and acknowledged the loss of the withdrawal right.
                </p>
              </div>
            </>
          ),
        },
        {
          id: 'acceptable-use',
          title: 'Acceptable Use',
          content: (
            <p>
              You agree to comply with the{' '}
              <Link to="/acceptable-use-policy" className="text-primary hover:underline">
                Acceptable Use Policy
              </Link>
              . You must not use the Service to publish content that is unlawful, fraudulent, deceptive, infringing,
              harassing, hateful, or harmful, and you must not attempt to abuse the rate limits, security, or integrity
              of the Service or of any connected platform.
            </p>
          ),
        },
        {
          id: 'intellectual-property',
          title: 'Intellectual Property',
          content: (
            <p>
              The Service, including its software, design, trademarks, and documentation, is owned by {SITE.brandName}.
              Subject to these Terms, we grant you a limited, non-exclusive, non-transferable, revocable licence to
              access and use the Service for your internal business or personal purposes. You may not reverse engineer,
              resell, sublicence, or white-label the Service, remove proprietary notices, or use the Service to build a
              competing product.
            </p>
          ),
        },
        {
          id: 'third-party',
          title: 'Third-Party Services',
          content: (
            <p>
              The Service integrates with third-party platforms and services. We are not responsible for any
              third-party service, and your use of such services is governed by their own terms. If a third-party
              platform changes or removes an API, we may have to change or discontinue the corresponding feature.
            </p>
          ),
        },
        {
          id: 'availability',
          title: 'Service Availability and Changes',
          content: (
            <p>
              We aim to keep the Service highly available but do not warrant uninterrupted access. We may modify,
              suspend, or discontinue any part of the Service at any time. We will give reasonable advance notice for
              material changes that adversely affect paying customers.
            </p>
          ),
        },
        {
          id: 'disclaimers',
          title: 'Disclaimers',
          content: (
            <p>
              THE SERVICE IS PROVIDED &quot;AS IS&quot; AND &quot;AS AVAILABLE&quot;, WITHOUT WARRANTIES OF ANY KIND,
              EXPRESS OR IMPLIED. WE DO NOT WARRANT THAT THE SERVICE WILL BE UNINTERRUPTED, ERROR-FREE, OR FREE OF
              HARMFUL COMPONENTS, OR THAT ANY CONTENT WILL BE ACCURATELY DELIVERED TO OR ACCEPTED BY ANY THIRD-PARTY
              PLATFORM.
            </p>
          ),
        },
        {
          id: 'liability',
          title: 'Limitation of Liability',
          content: (
            <>
              <p className="mb-3">
                TO THE MAXIMUM EXTENT PERMITTED BY LAW, {SITE.brandName.toUpperCase()} WILL NOT BE LIABLE FOR ANY
                INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR ANY LOSS OF PROFITS, REVENUE,
                DATA, GOODWILL, OR FOLLOWERS.
              </p>
              <p>
                OUR TOTAL AGGREGATE LIABILITY WILL NOT EXCEED THE GREATER OF (A) THE FEES YOU PAID TO {SITE.brandName}{' '}
                IN THE 12 MONTHS BEFORE THE EVENT GIVING RISE TO THE LIABILITY, OR (B) USD 100. NOTHING LIMITS
                LIABILITY THAT CANNOT BE LIMITED OR EXCLUDED BY APPLICABLE LAW.
              </p>
            </>
          ),
        },
        {
          id: 'indemnification',
          title: 'Indemnification',
          content: (
            <p>
              You agree to defend, indemnify, and hold harmless {SITE.brandName} from any claims, damages, liabilities,
              and expenses (including reasonable legal fees) arising out of your Customer Content, your breach of these
              Terms, or your violation of any law or third-party right.
            </p>
          ),
        },
        {
          id: 'termination',
          title: 'Termination',
          content: (
            <p>
              You may terminate these Terms at any time by closing your account. We may suspend or terminate your
              access immediately if you breach these Terms, fail to pay, or use the Service in a way that creates legal
              exposure. Sections that by their nature should survive termination (IP, disclaimers, limitation of
              liability, indemnification, governing law) will survive.
            </p>
          ),
        },
        {
          id: 'governing-law',
          title: 'Governing Law and Disputes',
          content: (
            <p>
              These Terms are governed by {SITE.legal.governingLaw}, without regard to conflict-of-law rules. The
              parties submit to the exclusive jurisdiction of {SITE.legal.courts}. If you are an EU consumer, you may
              also bring claims in the courts of your country of residence; mandatory consumer-protection laws of your
              country continue to apply.
            </p>
          ),
        },
        {
          id: 'changes',
          title: 'Changes to These Terms',
          content: (
            <p>
              We may update these Terms from time to time. We will post the revised version on this page, update the
              effective date, and for material changes notify you at least 14 days before they take effect.
            </p>
          ),
        },
        {
          id: 'contact',
          title: 'Contact',
          content: (
            <p>
              Questions about these Terms? Email{' '}
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
