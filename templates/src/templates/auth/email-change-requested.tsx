import * as React from 'react';
import { Heading, Section, Text } from '@react-email/components';
import { EmailLayout } from '../../components/layout.js';
import { EmailPrimaryButton } from '../../components/button.js';

void React;

export interface EmailChangeRequestedProps {
  oldEmail: string;
  newEmail: string;
  confirmUrl: string;
  expiresAt: string;
}

const content = { padding: '32px 36px 0' };

const heading = {
  fontSize: '24px',
  fontWeight: 700 as const,
  color: '#0F172A',
  letterSpacing: '-0.03em',
  margin: '0 0 14px',
  lineHeight: '1.2',
};

const bodyText = {
  fontSize: '15px',
  lineHeight: '26px',
  color: '#475569',
  margin: '0 0 10px',
};

const emailBadge = {
  display: 'inline-block' as const,
  backgroundColor: '#F8FAFC',
  padding: '4px 12px',
  borderRadius: '8px',
  fontFamily:
    'ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace',
  fontSize: '13px',
  fontWeight: 500 as const,
  color: '#334155',
  border: '1px solid #E2E8F0',
};

const muted = {
  fontSize: '13px',
  lineHeight: '22px',
  color: '#94A3B8',
};

export function EmailChangeRequestedEmail({
  oldEmail,
  newEmail,
  confirmUrl,
  expiresAt,
}: EmailChangeRequestedProps) {
  return (
    <EmailLayout
      previewText="Confirm your new TrendPulse email address"
      tagline="Security"
    >
      <Section style={content}>
        <Heading style={heading}>Confirm your new email</Heading>
        <Text style={bodyText}>
          You requested to change the email on your TrendPulse account:
        </Text>
        <Text style={{ ...bodyText, margin: '14px 0 6px' }}>
          <span style={{ color: '#94A3B8', fontSize: '12px' }}>From:</span>{' '}
          <span style={emailBadge}>{oldEmail}</span>
        </Text>
        <Text style={{ ...bodyText, margin: '6px 0 0' }}>
          <span style={{ color: '#94A3B8', fontSize: '12px' }}>To:</span>{' '}
          <span style={emailBadge}>{newEmail}</span>
        </Text>
        <Section style={{ marginTop: '24px' }}>
          <EmailPrimaryButton href={confirmUrl} label="Confirm new email" />
        </Section>
        <Text style={{ ...muted, marginTop: '20px' }}>
          This link expires {expiresAt}.
        </Text>
        <Text style={{ ...muted, marginTop: '16px' }}>
          If you did not request this change, ignore this email — your current
          address remains unchanged.
        </Text>
      </Section>
    </EmailLayout>
  );
}
