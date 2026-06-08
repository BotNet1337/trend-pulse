import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';
import { LegalPage } from './legal-page';

const ABUSE_EMAIL = SITE.legal.abuseEmail;

export function AcceptableUsePolicyPage() {
  return (
    <LegalPage
      title="Acceptable Use Policy"
      lastUpdated={SITE.legal.effectiveDate}
      intro={
        <p>
          This Acceptable Use Policy (&quot;AUP&quot;) governs your use of {SITE.brandName}. It is part of the{' '}
          <Link to="/terms-of-service" className="text-primary hover:underline">
            Terms of Service
          </Link>
          . We reserve the right to investigate, suspend, or terminate any account that violates this AUP.
        </p>
      }
      items={[
        {
          id: 'prohibited-content',
          title: 'Prohibited Content',
          defaultOpen: true,
          content: (
            <>
              <p className="mb-3">
                You must not use {SITE.brandName} to create, schedule, publish, distribute, or store content that:
              </p>
              <ul className="space-y-2">
                <li>is illegal under any law applicable to you, us, or your audience;</li>
                <li>
                  depicts or promotes child sexual abuse material (CSAM) — we report any such content to NCMEC and/or
                  local authorities;
                </li>
                <li>promotes terrorism, violent extremism, or organised criminal activity;</li>
                <li>incites violence, self-harm, or suicide;</li>
                <li>harasses, bullies, threatens, defames, or doxes any person or group;</li>
                <li>
                  promotes hate speech or discrimination based on race, ethnicity, national origin, religion,
                  disability, gender, gender identity, sexual orientation, age, or veteran status;
                </li>
                <li>infringes any intellectual-property right;</li>
                <li>impersonates any person or entity, or misrepresents your affiliation with anyone;</li>
                <li>contains malware, viruses, ransomware, exploit code, or links to such material;</li>
                <li>
                  contains sexually explicit material on platforms or in jurisdictions where it is prohibited;
                </li>
                <li>
                  promotes or facilitates illegal gambling, narcotic substances, weapons, or other illegal goods;
                </li>
                <li>
                  contains private or personal information about another person without their consent (PII, financial
                  data, medical data, sexual orientation, etc.).
                </li>
              </ul>
            </>
          ),
        },
        {
          id: 'prohibited-activities',
          title: 'Prohibited Activities',
          content: (
            <>
              <p className="mb-3">You must not, and must not allow any third party to:</p>
              <ul className="space-y-2">
                <li>spam, bulk-publish, mass-DM, or otherwise abuse the Service or any connected platform;</li>
                <li>
                  violate the terms of service, community guidelines, or API usage policies of any connected social
                  platform;
                </li>
                <li>
                  attempt to circumvent rate limits, captchas, or other abuse protections, on {SITE.brandName} or on
                  connected platforms;
                </li>
                <li>
                  automate engagement (likes, follows, comments) in a way that violates a connected platform&apos;s
                  automation rules;
                </li>
                <li>attempt to gain unauthorised access to any account, system, or network;</li>
                <li>
                  probe, scan, or test the vulnerability of the Service except under our published responsible-
                  disclosure policy;
                </li>
                <li>introduce malware, denial-of-service attacks, or other harmful code or traffic;</li>
                <li>
                  use the Service to send unsolicited commercial messages in violation of CAN-SPAM, CASL, GDPR, or
                  similar laws;
                </li>
                <li>resell, sublicence, or white-label the Service without our written consent;</li>
                <li>scrape, crawl, or extract data from the Service except as expressly permitted;</li>
                <li>
                  use the Service to build or train any machine-learning model that competes with {SITE.brandName}.
                </li>
              </ul>
            </>
          ),
        },
        {
          id: 'election-integrity',
          title: 'Election Integrity and Misinformation',
          content: (
            <>
              <p className="mb-3">You must not use {SITE.brandName} to:</p>
              <ul className="space-y-2">
                <li>
                  publish coordinated inauthentic content designed to mislead the public about elections, public-health
                  emergencies, or other matters of public concern;
                </li>
                <li>impersonate political candidates, election officials, or government bodies;</li>
                <li>
                  publish manipulated media (deepfakes, doctored images) without clearly labelling them as such, where
                  required by law or platform policy.
                </li>
              </ul>
            </>
          ),
        },
        {
          id: 'generative-ai',
          title: 'Use of Generative AI Features',
          content: (
            <p>
              If {SITE.brandName} offers AI-assisted writing, captioning, or image generation, you remain responsible
              for the content you publish. You must not use AI features to create content that violates this AUP or
              the policies of any connected platform.
            </p>
          ),
        },
        {
          id: 'reporting',
          title: 'Reporting Abuse',
          content: (
            <p>
              To report abuse of {SITE.brandName} — including spam, harassment, IP infringement, or CSAM — email{' '}
              <a href={`mailto:${ABUSE_EMAIL}`} className="text-primary hover:underline">
                {ABUSE_EMAIL}
              </a>
              . For copyright complaints, follow our DMCA-style notice procedure (include the work, the infringing URL,
              your contact info, a good-faith statement, and a sworn statement under penalty of perjury).
            </p>
          ),
        },
        {
          id: 'enforcement',
          title: 'Enforcement',
          content: (
            <>
              <p className="mb-3">Depending on the severity of a violation, we may:</p>
              <ol className="space-y-2 list-decimal pl-6">
                <li>Issue a warning.</li>
                <li>Remove or block specific content.</li>
                <li>Suspend the account temporarily.</li>
                <li>Terminate the account permanently and forfeit any unused fees.</li>
                <li>Cooperate with law-enforcement authorities.</li>
              </ol>
            </>
          ),
        },
        {
          id: 'changes',
          title: 'Changes',
          content: (
            <p>
              We may update this AUP at any time. The &quot;Last updated&quot; date above will reflect the current
              version.
            </p>
          ),
        },
      ]}
    />
  );
}
