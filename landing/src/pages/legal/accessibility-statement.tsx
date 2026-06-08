import { SITE } from '@/shared/site/constants';
import { LegalPage } from './legal-page';

const SUPPORT_EMAIL = SITE.contactEmail;

export function AccessibilityStatementPage() {
  return (
    <LegalPage
      title="Accessibility Statement"
      lastUpdated={SITE.legal.effectiveDate}
      intro={
        <p>
          {SITE.brandName} is committed to making our website and application accessible to as many people as
          possible, regardless of ability. We aim to meet WCAG 2.1 Level AA and to follow the European Accessibility
          Act (EAA), Section 508 of the US Rehabilitation Act, and EN 301 549 where applicable.
        </p>
      }
      items={[
        {
          id: 'conformance',
          title: 'Conformance Status',
          defaultOpen: true,
          content: (
            <p>
              The {SITE.brandName} website and application <strong>partially conform</strong> to WCAG 2.1 Level AA.
              &quot;Partially conformant&quot; means that some parts of the content do not yet fully meet the
              standard. We are actively working to fix any remaining gaps.
            </p>
          ),
        },
        {
          id: 'features',
          title: 'Accessibility Features',
          content: (
            <ul className="space-y-2">
              <li>Keyboard navigation for all interactive elements.</li>
              <li>Visible focus indicators that meet contrast requirements.</li>
              <li>Semantic HTML landmarks and ARIA roles where appropriate.</li>
              <li>Screen-reader support tested with VoiceOver, NVDA, and JAWS.</li>
              <li>Color contrast that meets WCAG AA for body text and UI components.</li>
              <li>Resizable text up to 200% without loss of functionality.</li>
              <li>Alt text on meaningful images.</li>
              <li>Reduced-motion preference respected for animations.</li>
              <li>Light and dark themes with sufficient contrast.</li>
            </ul>
          ),
        },
        {
          id: 'limitations',
          title: 'Known Limitations',
          content: (
            <ul className="space-y-2">
              <li>Some legacy onboarding flows have keyboard-trap issues we are fixing.</li>
              <li>Complex data tables (analytics) currently have limited screen-reader summaries.</li>
              <li>
                Third-party embeds (e.g., social media previews) inherit the accessibility of the source platform and
                may not be fully accessible.
              </li>
            </ul>
          ),
        },
        {
          id: 'assistive-tech',
          title: 'Assistive Technologies Tested',
          content: (
            <ul className="space-y-2">
              <li>
                <strong className="text-foreground">Screen readers:</strong> VoiceOver (macOS, iOS), NVDA (Windows),
                JAWS (Windows), TalkBack (Android).
              </li>
              <li>
                <strong className="text-foreground">Browsers:</strong> the latest two versions of Chrome, Firefox,
                Safari, and Edge.
              </li>
              <li>
                <strong className="text-foreground">Magnification:</strong> ZoomText and built-in OS magnifiers.
              </li>
            </ul>
          ),
        },
        {
          id: 'feedback',
          title: 'Feedback',
          content: (
            <>
              <p className="mb-3">
                We welcome feedback. If you encounter an accessibility barrier or need content in an alternative
                format, contact us:
              </p>
              <ul className="space-y-2">
                <li>
                  <strong className="text-foreground">Email:</strong>{' '}
                  <a href={`mailto:${SUPPORT_EMAIL}`} className="text-primary hover:underline">
                    {SUPPORT_EMAIL}
                  </a>
                </li>
                <li>We aim to respond within 5 business days.</li>
              </ul>
              <p className="mt-4 text-sm text-muted-foreground">
                When reporting an issue, please include the URL, a description of the problem, and the assistive
                technology and browser you were using.
              </p>
            </>
          ),
        },
        {
          id: 'ongoing',
          title: 'Ongoing Improvement',
          content: (
            <ul className="space-y-2">
              <li>Run automated accessibility checks (axe-core, Lighthouse) in CI.</li>
              <li>Commission periodic manual audits.</li>
              <li>Train our designers and developers on accessible practices.</li>
              <li>Prioritise fixes based on impact.</li>
            </ul>
          ),
        },
        {
          id: 'compatibility',
          title: 'Compatibility',
          content: (
            <p>
              {SITE.brandName} is designed to work with current browsers and assistive technologies. Some features may
              not work with very old browsers; we recommend keeping your browser and assistive technology up to date.
            </p>
          ),
        },
      ]}
    />
  );
}
