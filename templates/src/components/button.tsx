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

const button = {
  backgroundColor: '#2563eb',
  background: 'linear-gradient(135deg, #2563eb 0%, #7c3aed 100%)',
  borderRadius: '100px',
  color: '#fff',
  fontSize: '14px',
  fontWeight: '600' as const,
  letterSpacing: '0.01em',
  textDecoration: 'none',
  textAlign: 'center' as const,
  display: 'inline-block',
  padding: '14px 40px',
  boxShadow: '0 4px 20px rgba(37,99,235,0.35)',
};

export function EmailPrimaryButton({ href, label }: EmailButtonProps) {
  return (
    <EmailButton href={safeHref(href)} style={button}>
      {label}
    </EmailButton>
  );
}
