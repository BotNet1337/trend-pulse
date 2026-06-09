import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';
import { LegalPage } from './legal-page';

const PRIVACY_EMAIL = SITE.legal.privacyEmail;

export function CookiePolicyPage() {
  return (
    <LegalPage
      title="Cookie Policy"
      lastUpdated={SITE.legal.effectiveDate}
      intro={
        <p>
          This Cookie Policy explains how {SITE.brandName} uses cookies and similar technologies on our website and in
          the {SITE.brandName} application. It should be read together with our{' '}
          <Link to="/privacy-policy" className="text-primary hover:underline">
            Privacy Policy
          </Link>
          .
        </p>
      }
      items={[
        {
          id: 'what-are-cookies',
          title: 'What Are Cookies?',
          defaultOpen: true,
          content: (
            <>
              <p className="mb-3">
                Cookies are small text files placed on your device by a website. We also use{' '}
                <strong>localStorage</strong>, <strong>sessionStorage</strong>, and <strong>pixel tags</strong> — this
                Policy refers to all of them collectively as &quot;cookies&quot;.
              </p>
              <p>
                A cookie is <strong>first-party</strong> when it is set by the domain you are visiting and{' '}
                <strong>third-party</strong> when it is set by another domain. A cookie is a{' '}
                <strong>session cookie</strong> if it expires when you close your browser and a{' '}
                <strong>persistent cookie</strong> if it remains until its expiration date.
              </p>
            </>
          ),
        },
        {
          id: 'how-we-use',
          title: 'How We Use Cookies',
          content: (
            <>
              <p className="mb-3">We use cookies for four purposes:</p>
              <ul className="space-y-2">
                <li>
                  <strong className="text-foreground">Strictly necessary:</strong> authentication, session management,
                  CSRF protection, load balancing, and storing your cookie choices. Always on.
                </li>
                <li>
                  <strong className="text-foreground">Functional:</strong> remembering your preferences (theme,
                  language, time zone, dashboard layout).
                </li>
                <li>
                  <strong className="text-foreground">Analytics:</strong> understanding how the Service is used so we
                  can improve it. Opt-in in the EEA and UK.
                </li>
                <li>
                  <strong className="text-foreground">Marketing:</strong> measuring the performance of our marketing
                  campaigns. Opt-in.
                </li>
              </ul>
              <p className="mt-4">
                We do <strong>not</strong> use advertising cookies or third-party retargeting on the in-app experience.
              </p>
            </>
          ),
        },
        {
          id: 'cookies-we-set',
          title: 'Cookies We Set',
          content: (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left py-2 pr-4">Name</th>
                      <th className="text-left py-2 pr-4">Type</th>
                      <th className="text-left py-2 pr-4">Duration</th>
                      <th className="text-left py-2">Purpose</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-border/50">
                      <td className="py-2 pr-4 font-mono text-xs">tp_consent</td>
                      <td className="py-2 pr-4">Strictly necessary</td>
                      <td className="py-2 pr-4">12 months</td>
                      <td className="py-2">Stores your cookie choices</td>
                    </tr>
                    <tr className="border-b border-border/50">
                      <td className="py-2 pr-4 font-mono text-xs">tp_theme</td>
                      <td className="py-2 pr-4">Functional</td>
                      <td className="py-2 pr-4">12 months</td>
                      <td className="py-2">Light/dark theme</td>
                    </tr>
                    <tr className="border-b border-border/50">
                      <td className="py-2 pr-4 font-mono text-xs">tp_locale</td>
                      <td className="py-2 pr-4">Functional</td>
                      <td className="py-2 pr-4">12 months</td>
                      <td className="py-2">Language preference</td>
                    </tr>
                    <tr>
                      <td className="py-2 pr-4 font-mono text-xs">_ga, _ga_*</td>
                      <td className="py-2 pr-4">Analytics</td>
                      <td className="py-2 pr-4">Up to 24 months</td>
                      <td className="py-2">Google Analytics 4</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="mt-4 text-sm text-muted-foreground">
                The exact list may change as we add or remove tools. The most up-to-date list is shown in the cookie
                banner.
              </p>
            </>
          ),
        },
        {
          id: 'third-party',
          title: 'Third-Party Services',
          content: (
            <>
              <p className="mb-3">Some of our third-party providers may set their own cookies when their scripts run on our site:</p>
              <ul className="space-y-2">
                <li>
                  <strong className="text-foreground">Google Analytics 4</strong> — usage analytics.
                </li>
                <li>
                  <strong className="text-foreground">Sentry</strong> — error monitoring (may use localStorage).
                </li>
              </ul>
              <p className="mt-4">
                We require all subprocessors to use cookies only for the purposes we specify.
              </p>
            </>
          ),
        },
        {
          id: 'managing',
          title: 'Managing Your Preferences',
          content: (
            <ul className="space-y-2">
              <li>
                <strong className="text-foreground">Cookie banner.</strong> When you first visit, we show a banner
                where you can accept all, reject all (except strictly necessary), or choose categories.
              </li>
              <li>
                <strong className="text-foreground">In-app settings.</strong> You can change your choices at any time
                from Settings → Privacy.
              </li>
              <li>
                <strong className="text-foreground">Browser controls.</strong> Most browsers let you block or delete
                cookies. Blocking strictly necessary cookies may break login.
              </li>
              <li>
                <strong className="text-foreground">Global Privacy Control (GPC).</strong> We honour the GPC signal —
                see{' '}
                <Link to="/do-not-sell-or-share" className="text-primary hover:underline">
                  Do Not Sell or Share My Personal Information
                </Link>
                .
              </li>
            </ul>
          ),
        },
        {
          id: 'dnt',
          title: 'Do Not Track',
          content: (
            <p>
              There is no agreed industry standard for Do Not Track signals. We respect your cookie choices made in our
              banner and the GPC signal.
            </p>
          ),
        },
        {
          id: 'contact',
          title: 'Contact',
          content: (
            <p>
              Questions? Email{' '}
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
