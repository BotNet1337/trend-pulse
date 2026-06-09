import * as React from 'react';
import { Mail, MessageSquare } from 'lucide-react';
import { SITE } from '@/shared/site/constants';

export function ContactSection() {
  return (
    <section id="contact" className="py-24 px-6 lg:px-20 bg-muted/20">
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Get in Touch</h2>
          <p className="text-lg text-muted-foreground">Have questions? We&apos;d love to hear from you.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-2xl mx-auto">
          <div className="bg-card border border-border rounded-lg p-6">
            <div className="w-12 h-12 bg-primary/10 rounded-lg flex items-center justify-center mb-4">
              <Mail className="h-6 w-6 text-primary" />
            </div>
            <h3 className="mb-2">Email</h3>
            <p className="text-sm text-muted-foreground mb-2">Our team typically responds within 24 hours.</p>
            <a href={`mailto:${SITE.contactEmail}`} className="text-sm text-primary hover:underline">
              {SITE.contactEmail}
            </a>
          </div>

          <div className="bg-card border border-border rounded-lg p-6">
            <div className="w-12 h-12 bg-primary/10 rounded-lg flex items-center justify-center mb-4">
              <MessageSquare className="h-6 w-6 text-primary" />
            </div>
            <h3 className="mb-2">Support</h3>
            <p className="text-sm text-muted-foreground">
              Pro and Team customers get priority support at the same address.
            </p>
          </div>
        </div>

        <div className="mt-10 text-center">
          <a
            href={`mailto:${SITE.contactEmail}`}
            className="inline-flex items-center gap-2 bg-primary text-primary-foreground px-6 py-3 rounded-lg font-medium hover:bg-primary/90 transition-colors"
          >
            <Mail className="h-4 w-4" />
            Send us an email
          </a>
        </div>
      </div>
    </section>
  );
}
