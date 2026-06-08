import * as React from 'react';
import { Mail, MessageSquare } from 'lucide-react';
import { Button } from '@/shared/components/button';
import { Input } from '@/shared/components/input';
import { Textarea } from '@/shared/components/textarea';
import { Label } from '@/shared/components/label';
import { SITE } from '@/shared/site/constants';

type Status = 'idle' | 'submitting' | 'success' | 'error';

export function ContactSection() {
  const [status, setStatus] = React.useState<Status>('idle');
  const [formData, setFormData] = React.useState({
    name: '',
    email: '',
    company: '',
    message: '',
  });
  const isSubmitting = status === 'submitting';
  const isSuccess = status === 'success';
  const isDisabled = isSubmitting || isSuccess;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setStatus('submitting');
    try {
      const res = await fetch('/api/waitlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: formData.email, name: formData.name.trim() || undefined }),
      });
      if (!res.ok) throw new Error('bad_status');
      setStatus('success');
    } catch {
      setStatus('error');
    }
  }

  return (
    <section id="contact" className="py-24 px-6 lg:px-20 bg-muted/20">
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Get in Touch</h2>
          <p className="text-lg text-muted-foreground">Have questions? We&apos;d love to hear from you.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <div className="space-y-6">
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
                Pro and Enterprise customers get priority support at the same address.
              </p>
            </div>
          </div>

          <div className="md:col-span-2">
            <form onSubmit={handleSubmit} className="bg-card border border-border rounded-lg p-8">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <div className="space-y-2">
                  <Label htmlFor="name">Name *</Label>
                  <Input
                    id="name"
                    required
                    disabled={isDisabled}
                    value={formData.name}
                    onChange={(e) => setFormData((p) => ({ ...p, name: e.target.value }))}
                    autoComplete="name"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="email">Email *</Label>
                  <Input
                    id="email"
                    type="email"
                    required
                    disabled={isDisabled}
                    value={formData.email}
                    onChange={(e) => setFormData((p) => ({ ...p, email: e.target.value }))}
                    autoComplete="email"
                  />
                </div>
              </div>

              <div className="space-y-2 mb-4">
                <Label htmlFor="company">Company</Label>
                <Input
                  id="company"
                  disabled={isDisabled}
                  value={formData.company}
                  onChange={(e) => setFormData((p) => ({ ...p, company: e.target.value }))}
                  autoComplete="organization"
                />
              </div>

              <div className="space-y-2 mb-6">
                <Label htmlFor="message">Message *</Label>
                <Textarea
                  id="message"
                  required
                  rows={6}
                  disabled={isDisabled}
                  value={formData.message}
                  onChange={(e) => setFormData((p) => ({ ...p, message: e.target.value }))}
                />
              </div>

              <Button type="submit" className="w-full" disabled={isDisabled || isSubmitting}>
                {isSubmitting ? 'Sending…' : isSuccess ? 'Sent' : 'Send Message'}
              </Button>

              <div className="mt-4" aria-live="polite">
                {status === 'success' ? (
                  <p className="text-sm text-primary">Thanks. We&apos;ll reach out soon.</p>
                ) : null}
                {status === 'error' ? (
                  <p className="text-sm text-destructive">Something went wrong. Please email {SITE.contactEmail}.</p>
                ) : null}
              </div>

              <p className="text-xs text-muted-foreground mt-4">
                By submitting this form, you agree to our Privacy Policy. We&apos;ll only use your information to respond to
                your inquiry.
              </p>
            </form>
          </div>
        </div>
      </div>
    </section>
  );
}


