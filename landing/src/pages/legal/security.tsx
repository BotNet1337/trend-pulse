import { CheckCircle, Lock, Shield } from 'lucide-react';
import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';
import { LegalPage } from './legal-page';

const SECURITY_EMAIL = SITE.legal.securityEmail;
const SUPPORT_EMAIL = SITE.contactEmail;

export function SecurityPage() {
  return (
    <LegalPage
      title="Security & Compliance"
      lastUpdated={SITE.legal.effectiveDate}
      intro={
        <p>
          {SITE.brandName} is built and operated with security in mind. This page summarises our approach to keeping
          your data safe. It complements the technical and organisational measures listed in Schedule 1 of our{' '}
          <Link to="/dpa" className="text-primary hover:underline">
            Data Processing Agreement
          </Link>
          .
        </p>
      }
      top={
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-card border border-border rounded-lg p-6 text-center">
            <Shield className="h-10 w-10 text-primary mx-auto mb-3" />
            <h3 className="font-semibold mb-2">Encryption Everywhere</h3>
            <p className="text-sm text-muted-foreground">TLS 1.2+ in transit, strong encryption at rest</p>
          </div>
          <div className="bg-card border border-border rounded-lg p-6 text-center">
            <Lock className="h-10 w-10 text-primary mx-auto mb-3" />
            <h3 className="font-semibold mb-2">Least-Privilege Access</h3>
            <p className="text-sm text-muted-foreground">Mandatory MFA and audit logs for all production access</p>
          </div>
          <div className="bg-card border border-border rounded-lg p-6 text-center">
            <CheckCircle className="h-10 w-10 text-primary mx-auto mb-3" />
            <h3 className="font-semibold mb-2">GDPR / CCPA Ready</h3>
            <p className="text-sm text-muted-foreground">Transparent policies, user rights, and DPA on request</p>
          </div>
        </div>
      }
      items={[
        {
          id: 'encryption',
          title: 'Encryption',
          defaultOpen: true,
          content: (
            <ul className="space-y-2">
              <li>
                <strong className="text-foreground">In transit.</strong> All connections use TLS 1.2 or higher with
                modern cipher suites. HSTS is enabled on the website.
              </li>
              <li>
                <strong className="text-foreground">At rest.</strong> Databases, object storage, and backups are
                encrypted using strong symmetric encryption.
              </li>
              <li>
                <strong className="text-foreground">Secrets.</strong> OAuth tokens, API keys, and other secrets are
                encrypted at the application layer using a managed key-management service. Secrets are never logged.
              </li>
            </ul>
          ),
        },
        {
          id: 'infrastructure',
          title: 'Infrastructure',
          content: (
            <p>
              {SITE.brandName} runs on managed cloud infrastructure in the European Union. Production services run in
              private networks; only the load balancer is exposed to the public internet. We use redundant zones,
              automated failover, daily backups, and a documented disaster-recovery plan.
            </p>
          ),
        },
        {
          id: 'application-security',
          title: 'Application Security',
          content: (
            <ul className="space-y-2">
              <li>Mandatory peer code review for all changes to production code.</li>
              <li>Automated dependency-vulnerability scanning on every build.</li>
              <li>Static analysis and secret scanning in CI.</li>
              <li>
                Security headers: Content Security Policy, Strict-Transport-Security, X-Frame-Options, Referrer-Policy,
                Permissions-Policy.
              </li>
              <li>Input validation, output encoding, parameterised queries.</li>
              <li>Rate limiting and abuse detection on authentication and publishing endpoints.</li>
            </ul>
          ),
        },
        {
          id: 'identity-access',
          title: 'Identity and Access',
          content: (
            <ul className="space-y-2">
              <li>
                <strong className="text-foreground">Customer accounts.</strong> Salted password hashing (Argon2 or
                bcrypt with high work factor), optional two-factor authentication, session expiry, suspicious-login
                alerts.
              </li>
              <li>
                <strong className="text-foreground">Internal access.</strong> MFA enforced for all engineers with
                access to production; SSO with audit logs; principle of least privilege; periodic access reviews.
              </li>
            </ul>
          ),
        },
        {
          id: 'monitoring',
          title: 'Monitoring and Logging',
          content: (
            <ul className="space-y-2">
              <li>Centralised application and infrastructure logs.</li>
              <li>Tamper-evident retention for security-relevant logs.</li>
              <li>Alerting on anomalous activity (failed logins, privilege changes, unusual API patterns).</li>
            </ul>
          ),
        },
        {
          id: 'incident-response',
          title: 'Incident Response',
          content: (
            <>
              <p className="mb-3">
                We maintain a documented incident-response plan covering detection, triage, containment, eradication,
                recovery, and post-mortem. We commit to notifying affected customers without undue delay and within
                72 hours when a Personal Data Breach is confirmed, in line with GDPR Article 33.
              </p>
              <p>
                To report a vulnerability or suspected incident, email{' '}
                <a href={`mailto:${SECURITY_EMAIL}`} className="text-primary hover:underline">
                  {SECURITY_EMAIL}
                </a>
                . We follow a coordinated-disclosure approach: please give us reasonable time to investigate and
                remediate before public disclosure.
              </p>
            </>
          ),
        },
        {
          id: 'privacy-compliance',
          title: 'Privacy and Compliance',
          content: (
            <ul className="space-y-2">
              <li>
                <strong className="text-foreground">GDPR / UK GDPR / Swiss FADP.</strong> We act as data controller for
                account data and as data processor for content the Customer publishes. See the{' '}
                <Link to="/privacy-policy" className="text-primary hover:underline">
                  Privacy Policy
                </Link>{' '}
                and{' '}
                <Link to="/dpa" className="text-primary hover:underline">
                  DPA
                </Link>
                .
              </li>
              <li>
                <strong className="text-foreground">CCPA / CPRA.</strong> California residents have additional rights
                — see{' '}
                <Link to="/do-not-sell-or-share" className="text-primary hover:underline">
                  Do Not Sell or Share My Personal Information
                </Link>
                .
              </li>
              <li>
                <strong className="text-foreground">Ukrainian Law on Personal Data Protection.</strong>{' '}
                {SITE.brandName} complies with the Ukrainian Law &quot;On Personal Data Protection&quot; as the
                operating entity is based in {SITE.legal.jurisdiction}.
              </li>
            </ul>
          ),
        },
        {
          id: 'subprocessor-security',
          title: 'Subprocessor Security',
          content: (
            <p>
              We assess each subprocessor&apos;s security posture before onboarding and require contractual
              data-protection obligations. The current subprocessor list is in Schedule 2 of the{' '}
              <Link to="/dpa" className="text-primary hover:underline">
                DPA
              </Link>
              .
            </p>
          ),
        },
        {
          id: 'your-responsibilities',
          title: 'Your Security Responsibilities',
          content: (
            <ul className="space-y-2">
              <li>Choose a strong, unique password and enable two-factor authentication.</li>
              <li>Keep your access credentials confidential.</li>
              <li>Promptly disconnect compromised social-media accounts and revoke exposed tokens.</li>
              <li>
                Report suspicious activity to{' '}
                <a href={`mailto:${SECURITY_EMAIL}`} className="text-primary hover:underline">
                  {SECURITY_EMAIL}
                </a>
                .
              </li>
            </ul>
          ),
        },
        {
          id: 'contact',
          title: 'Contact',
          content: (
            <ul className="space-y-2">
              <li>
                <strong className="text-foreground">Security reports / coordinated disclosure:</strong>{' '}
                <a href={`mailto:${SECURITY_EMAIL}`} className="text-primary hover:underline">
                  {SECURITY_EMAIL}
                </a>
              </li>
              <li>
                <strong className="text-foreground">General security questions:</strong>{' '}
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
