import * as React from 'react';
import { Button as EmailButton } from '@react-email/components';

void React;

/**
 * Allow only http(s) URLs in email links. react-email escapes text content but
 * NOT the `href` scheme, so a `javascript:`/`data:` URL in a url-prop would render
 * a clickable XSS/phishing link. Anything that is not http(s) collapses to `#`.
 */
export function safeHref(url: string): string {
  return /^https?:\/\//i.test(url) ? url : '#';
}

export interface EmailButtonProps {
  href: string;
  label: string;
}

const button = {
  backgroundColor: '#6366F1',
  background: 'linear-gradient(140deg, #6366F1 0%, #8B5CF6 100%)',
  borderRadius: '100px',
  color: '#fff',
  fontSize: '14px',
  fontWeight: '600' as const,
  letterSpacing: '0.01em',
  textDecoration: 'none',
  textAlign: 'center' as const,
  display: 'inline-block',
  padding: '14px 40px',
  boxShadow: '0 4px 14px rgba(99,102,241,0.25)',
};

export function EmailPrimaryButton({ href, label }: EmailButtonProps) {
  return (
    <EmailButton href={safeHref(href)} style={button}>
      {label}
    </EmailButton>
  );
}
