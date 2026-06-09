import { Eye, FileCheck, Globe, Lock, Shield, Trash2 } from 'lucide-react';
import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';

export function SecurityPrivacySection() {
  const highlights = [
    {
      icon: Eye,
      title: 'Public channels only',
      description:
        'We monitor only public Telegram channels (accessible via @username). Private channels and personal messages are never accessed.',
    },
    {
      icon: Trash2,
      title: '48-hour raw content limit',
      description:
        'Raw message content is automatically discarded within 48 hours. Only trend signals and metadata are retained for history.',
    },
    {
      icon: Shield,
      title: 'GDPR baseline',
      description: 'We maintain privacy terms and data subject rights handling as a baseline, governed by Ukrainian law.',
    },
    {
      icon: Lock,
      title: 'Reasonable security practices',
      description: 'Practical security controls — encryption in transit, access controls, and audit logging — without over-promising.',
    },
    {
      icon: FileCheck,
      title: 'Data Processing Agreement',
      description: 'Clear terms for how your data is processed and stored. Available on request.',
    },
    {
      icon: Globe,
      title: 'Do Not Sell / Share',
      description: 'We do not sell your personal data. CCPA/CPRA opt-out information is available for California residents.',
    },
  ];

  return (
    <section id="security-privacy" className="py-24 px-6 lg:px-20 snap-start scroll-mt-16">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Security &amp; Privacy First</h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            {SITE.brandName} is designed around compliance from day one — public channels only, 48-hour retention, honest policies.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {highlights.map((highlight) => {
            const Icon = highlight.icon;
            return (
              <div
                key={highlight.title}
                className="group bg-card border border-border rounded-lg p-6 flex gap-4 transition-all hover:shadow-md hover:border-primary/50 hover:-translate-y-0.5"
              >
                <div className="w-12 h-12 bg-primary/10 rounded-lg flex items-center justify-center shrink-0 transition-colors group-hover:bg-primary/20">
                  <Icon className="h-6 w-6 text-primary" aria-hidden="true" />
                </div>
                <div>
                  <h3 className="mb-2">{highlight.title}</h3>
                  <p className="text-sm text-muted-foreground">{highlight.description}</p>
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-8 bg-muted/50 border border-border rounded-lg p-6 text-center">
          <p className="text-sm text-muted-foreground">
            <strong>Note:</strong> {SITE.brandName} is in active development. Please review our{' '}
            <Link to="/security" className="text-primary hover:underline">
              Security Policy
            </Link>{' '}
            and{' '}
            <Link to="/privacy-policy" className="text-primary hover:underline">
              Privacy Policy
            </Link>{' '}
            for current details.
          </p>
        </div>
      </div>
    </section>
  );
}


