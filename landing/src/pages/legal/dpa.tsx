import { SITE } from '@/shared/site/constants';
import { LegalPage } from './legal-page';

const PRIVACY_EMAIL = SITE.legal.privacyEmail;

export function DpaOverviewPage() {
  return (
    <LegalPage
      title="Data Processing Agreement"
      lastUpdated={SITE.legal.effectiveDate}
      intro={
        <p>
          This Data Processing Agreement (&quot;DPA&quot;) forms part of the Terms of Service between{' '}
          {SITE.legal.entityName} (&quot;{SITE.brandName}&quot;, &quot;Processor&quot;) and the Customer
          (&quot;Controller&quot;). It applies to the extent {SITE.brandName} processes Personal Data on behalf of the
          Customer. If you require a counter-signed copy, email{' '}
          <a href={`mailto:${PRIVACY_EMAIL}`} className="text-primary hover:underline">
            {PRIVACY_EMAIL}
          </a>
          .
        </p>
      }
      items={[
        {
          id: 'definitions',
          title: 'Definitions',
          defaultOpen: true,
          content: (
            <ul className="space-y-2">
              <li>
                <strong className="text-foreground">Applicable Data Protection Law</strong> — the EU GDPR, UK GDPR,
                Swiss FADP, Ukrainian Law on Personal Data Protection, CCPA/CPRA, and similar.
              </li>
              <li>
                <strong className="text-foreground">Controller / Processor / Personal Data / Data Subject / Processing
                / Personal Data Breach</strong> — as defined in the GDPR.
              </li>
              <li>
                <strong className="text-foreground">Customer Personal Data</strong> — Personal Data that{' '}
                {SITE.brandName} processes on behalf of the Customer.
              </li>
              <li>
                <strong className="text-foreground">Sub-processor</strong> — any processor engaged by {SITE.brandName}{' '}
                to process Customer Personal Data.
              </li>
            </ul>
          ),
        },
        {
          id: 'scope',
          title: 'Scope and Roles',
          content: (
            <>
              <p className="mb-3">
                The Customer is the Controller and {SITE.brandName} is the Processor of Customer Personal Data.
              </p>
              <h3 className="font-semibold text-foreground mb-2 mt-4">Subject matter, nature, and purpose</h3>
              <p className="mb-3">
                Provision of the {SITE.brandName} cross-platform social media publishing service: storing content,
                scheduling, publishing to third-party platforms on behalf of the Customer, and reporting on outcomes.
              </p>
              <h3 className="font-semibold text-foreground mb-2 mt-4">Categories of Data Subjects</h3>
              <p className="mb-3">
                End users of the Customer&apos;s social-media accounts; the Customer&apos;s team members; individuals
                who appear in or interact with content the Customer publishes.
              </p>
              <h3 className="font-semibold text-foreground mb-2 mt-4">Categories of Personal Data</h3>
              <p>
                Identification data, authentication tokens for connected platforms, content provided by the Customer,
                engagement metrics, IP addresses, and device data.
              </p>
            </>
          ),
        },
        {
          id: 'instructions',
          title: 'Customer Instructions',
          content: (
            <p>
              {SITE.brandName} will process Customer Personal Data only on documented instructions from the Customer,
              including those set out in the Terms, this DPA, and the configuration choices the Customer makes in the
              Service. {SITE.brandName} will inform the Customer if an instruction infringes Applicable Data Protection
              Law.
            </p>
          ),
        },
        {
          id: 'confidentiality',
          title: 'Confidentiality',
          content: (
            <p>
              {SITE.brandName} ensures that personnel authorised to process Customer Personal Data are bound by
              confidentiality obligations and trained on data-protection requirements.
            </p>
          ),
        },
        {
          id: 'security-measures',
          title: 'Security (Schedule 1)',
          content: (
            <>
              <p className="mb-3">{SITE.brandName} implements the following technical and organisational measures:</p>
              <ul className="space-y-2">
                <li>
                  <strong className="text-foreground">Encryption.</strong> TLS 1.2+ in transit; AES-256 at rest;
                  encryption of OAuth tokens at the application layer.
                </li>
                <li>
                  <strong className="text-foreground">Access control.</strong> RBAC; least privilege; mandatory MFA;
                  SSO with audit logs.
                </li>
                <li>
                  <strong className="text-foreground">Network security.</strong> Private networks; firewalls;
                  segmentation of production from staging; DDoS mitigation.
                </li>
                <li>
                  <strong className="text-foreground">Application security.</strong> Code review, dependency scanning,
                  automated testing, secret scanning in CI, security headers.
                </li>
                <li>
                  <strong className="text-foreground">Operational security.</strong> Centralised logging, alerting on
                  anomalies, infrastructure as code, change management.
                </li>
                <li>
                  <strong className="text-foreground">Backups and recovery.</strong> Daily encrypted backups, restore
                  testing, documented disaster-recovery procedures.
                </li>
                <li>
                  <strong className="text-foreground">Incident response.</strong> Documented plan; on-call rotation;
                  72-hour breach notification commitment.
                </li>
              </ul>
            </>
          ),
        },
        {
          id: 'subprocessors',
          title: 'Sub-processors (Schedule 2)',
          content: (
            <>
              <p className="mb-3">
                The Customer authorises {SITE.brandName} to engage the following Sub-processors. We give at least 14
                days&apos; advance notice of changes.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left py-2 pr-4">Sub-processor</th>
                      <th className="text-left py-2 pr-4">Service</th>
                      <th className="text-left py-2">Location</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-border/50">
                      <td className="py-2 pr-4">Hetzner Online GmbH</td>
                      <td className="py-2 pr-4">Cloud hosting</td>
                      <td className="py-2">Germany / Finland</td>
                    </tr>
                    <tr className="border-b border-border/50">
                      <td className="py-2 pr-4">Cloudflare, Inc.</td>
                      <td className="py-2 pr-4">CDN, DNS, DDoS mitigation</td>
                      <td className="py-2">Global</td>
                    </tr>
                    <tr className="border-b border-border/50">
                      <td className="py-2 pr-4">Stripe Payments Europe, Ltd.</td>
                      <td className="py-2 pr-4">Payment processing</td>
                      <td className="py-2">Ireland / US</td>
                    </tr>
                    <tr className="border-b border-border/50">
                      <td className="py-2 pr-4">Amazon Web Services, Inc.</td>
                      <td className="py-2 pr-4">Object storage, email</td>
                      <td className="py-2">EU regions</td>
                    </tr>
                    <tr className="border-b border-border/50">
                      <td className="py-2 pr-4">Google LLC (GA4)</td>
                      <td className="py-2 pr-4">Website analytics</td>
                      <td className="py-2">US</td>
                    </tr>
                    <tr>
                      <td className="py-2 pr-4">Sentry, Inc.</td>
                      <td className="py-2 pr-4">Error monitoring</td>
                      <td className="py-2">EU region</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="mt-4 text-sm text-muted-foreground">
                Request the current list at any time by emailing {PRIVACY_EMAIL}.
              </p>
            </>
          ),
        },
        {
          id: 'data-subject-rights',
          title: 'Data Subject Rights',
          content: (
            <p>
              {SITE.brandName} will, taking into account the nature of the processing, assist the Customer by
              appropriate technical and organisational measures in fulfilling the Customer&apos;s obligation to respond
              to Data Subject requests. If a Data Subject contacts {SITE.brandName} directly, we will forward the
              request to the Customer.
            </p>
          ),
        },
        {
          id: 'breach-notification',
          title: 'Personal Data Breach Notification',
          content: (
            <p>
              {SITE.brandName} will notify the Customer without undue delay and in any case within 72 hours after
              becoming aware of a Personal Data Breach affecting Customer Personal Data, and will provide information
              reasonably necessary to enable the Customer to meet its own notification obligations.
            </p>
          ),
        },
        {
          id: 'return-deletion',
          title: 'Return and Deletion',
          content: (
            <p>
              On termination or expiry of the Service, {SITE.brandName} will, at the Customer&apos;s choice, delete or
              return all Customer Personal Data within 30 days, except for backups, which are deleted on the standard
              backup-rotation schedule (up to 35 days), or where retention is required by law.
            </p>
          ),
        },
        {
          id: 'audits',
          title: 'Audits',
          content: (
            <p>
              {SITE.brandName} will make available to the Customer information reasonably necessary to demonstrate
              compliance with this DPA, and allow for and contribute to audits no more than once per year, subject to
              reasonable confidentiality and security restrictions.
            </p>
          ),
        },
        {
          id: 'international-transfers',
          title: 'International Transfers',
          content: (
            <p>
              Where {SITE.brandName} transfers Customer Personal Data outside the EEA, UK, or Switzerland to a country
              without an adequacy decision, the parties agree that the European Commission&apos;s Standard Contractual
              Clauses (Module Two or Three, as applicable) apply, supplemented by the UK Addendum where relevant.
            </p>
          ),
        },
        {
          id: 'precedence',
          title: 'Order of Precedence',
          content: (
            <p>
              In the event of a conflict between this DPA and the Terms, this DPA prevails with respect to the
              processing of Customer Personal Data. Liability under this DPA is subject to the limitations set out in
              the Terms of Service.
            </p>
          ),
        },
        {
          id: 'contact',
          title: 'Contact',
          content: (
            <p>
              DPA questions or requests?{' '}
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
