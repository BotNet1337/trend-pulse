import * as React from 'react';
import { Mail, MessageSquare } from 'lucide-react';
import { SITE } from '@/shared/site/constants';

export function ContactSection() {
  return (
    <section id="contact" className="py-20 md:py-24 px-6 lg:px-20">
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-12">
          <p className="fs-eyebrow justify-center mb-4">Contact</p>
          <h2 className="text-3xl md:text-4xl font-bold mb-4">
            Get in <span className="fs-grad-text">Touch</span>
          </h2>
          <p className="text-lg text-muted-foreground">Have questions? We&apos;d love to hear from you.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5 max-w-2xl mx-auto">
          <div className="fs-glass fs-card-hover p-6">
            <span className="fs-feature-icon mb-4 flex h-12 w-12 items-center justify-center rounded-[14px]">
              <Mail className="h-5 w-5" />
            </span>
            <h3 className="mb-2 text-lg font-bold">Email</h3>
            <p className="text-sm text-muted-foreground mb-2">Our team typically responds within 24 hours.</p>
            <a href={`mailto:${SITE.contactEmail}`} className="text-sm text-primary hover:underline">
              {SITE.contactEmail}
            </a>
          </div>

          <div className="fs-glass fs-card-hover p-6">
            <span className="fs-feature-icon mb-4 flex h-12 w-12 items-center justify-center rounded-[14px]">
              <MessageSquare className="h-5 w-5" />
            </span>
            <h3 className="mb-2 text-lg font-bold">Support</h3>
            <p className="text-sm text-muted-foreground">
              Pro and Team customers get priority support at the same address.
            </p>
          </div>
        </div>

        <div className="mt-10 text-center">
          <a
            href={`mailto:${SITE.contactEmail}`}
            className="inline-flex items-center gap-2 rounded-full bg-aurora-button px-6 py-3 font-semibold text-primary-foreground shadow-[0_4px_24px_rgba(99,102,241,0.35)] transition-all duration-200 hover:-translate-y-0.5 hover:bg-aurora-button-hover hover:shadow-[0_8px_32px_rgba(99,102,241,0.45)]"
          >
            <Mail className="h-4 w-4" />
            Send us an email
          </a>
        </div>
      </div>
    </section>
  );
}
