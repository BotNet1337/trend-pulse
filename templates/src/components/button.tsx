import * as React from 'react';
import { Button as EmailButton } from '@react-email/components';

void React;

export function safeHref(url: string): string {
  return /^https?:\/\//i.test(url) ? url : '#';
}

export interface EmailButtonProps {
  href: string;
  label: string;
}

// Bulletproof gradient CTA (solid #4f46e5 fallback for Outlook / no-gradient clients)
const button = {
  backgroundColor: '#4f46e5',
  background: 'linear-gradient(135deg,#2563eb 0%,#7c3aed 100%)',
  borderRadius: '999px',
  color: '#ffffff',
  fontSize: '14px',
  fontWeight: '600' as const,
  letterSpacing: '0.01em',
  textDecoration: 'none',
  textAlign: 'center' as const,
  display: 'inline-block',
  padding: '14px 40px',
};

export function EmailPrimaryButton({ href, label }: EmailButtonProps) {
  return (
    <EmailButton href={safeHref(href)} style={button}>
      {label}
    </EmailButton>
  );
}
