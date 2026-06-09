import * as React from 'react';
import { Heading, Section, Text } from '@react-email/components';
import { EmailLayout } from '../../components/layout.js';

void React;

export interface EmailChangedNoticeProps {
  oldEmail: string;
  newEmail: string;
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

const dangerBox = {
  fontSize: '13px',
  lineHeight: '22px',
  color: '#DC2626',
  backgroundColor: '#FEF2F2',
  padding: '14px 20px',
  borderRadius: '14px',
  border: '1px solid #FECACA',
  marginTop: '24px',
};

export function EmailChangedNoticeEmail({
  oldEmail,
  newEmail,
}: EmailChangedNoticeProps) {
  return (
    <EmailLayout
      previewText="Your TrendPulse email was changed"
      tagline="Security alert"
    >
      <Section style={content}>
        <Heading style={heading}>Email updated</Heading>
        <Text style={bodyText}>
          Your account email was changed successfully.
        </Text>
        <Text style={{ ...bodyText, margin: '14px 0 6px' }}>
          <span style={{ color: '#94A3B8', fontSize: '12px' }}>
            Previous:
          </span>{' '}
          <span style={emailBadge}>{oldEmail}</span>
        </Text>
        <Text style={{ ...bodyText, margin: '6px 0 0' }}>
          <span style={{ color: '#94A3B8', fontSize: '12px' }}>Current:</span>{' '}
          <span style={emailBadge}>{newEmail}</span>
        </Text>
        <Text style={{ ...bodyText, marginTop: '16px' }}>
          Sign in with your new address from now on.
        </Text>
        <Text style={dangerBox}>
          If this wasn&apos;t you, contact support immediately — your account
          may be compromised.
        </Text>
      </Section>
    </EmailLayout>
  );
}
