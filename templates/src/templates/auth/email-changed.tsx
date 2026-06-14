import * as React from 'react';
import { Heading, Section, Text } from '@react-email/components';
import { EmailLayout } from '../../components/layout.js';

void React;

export interface EmailChangedNoticeProps {
  oldEmail: string;
  newEmail: string;
}

const content = {
  backgroundColor: '#ffffff',
  padding: '32px 36px 0',
};

const heading = {
  fontSize: '24px',
  fontWeight: 700 as const,
  color: '#0f172a',
  letterSpacing: '-0.03em',
  margin: '0 0 14px',
  lineHeight: '1.25',
};

const bodyText = {
  fontSize: '15px',
  lineHeight: '26px',
  color: '#475569',
  margin: '0 0 10px',
};

const emailLabel = {
  color: '#94a3b8',
  fontSize: '12px',
};

const emailBadge = {
  display: 'inline-block' as const,
  backgroundColor: '#f8fafc',
  padding: '4px 12px',
  borderRadius: '8px',
  fontFamily:
    'ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace',
  fontSize: '13px',
  fontWeight: 500 as const,
  color: '#334155',
  border: '1px solid #e2e8f0',
};

const dangerBox = {
  fontSize: '13px',
  lineHeight: '22px',
  color: '#dc2626',
  backgroundColor: '#fef2f2',
  padding: '14px 20px',
  borderRadius: '14px',
  border: '1px solid #fecaca',
  marginTop: '24px',
};

export function EmailChangedNoticeEmail({
  oldEmail,
  newEmail,
}: EmailChangedNoticeProps) {
  return (
    <EmailLayout
      previewText="Your Foresignal email was changed"
      tagline="Security alert"
    >
      <Section style={content}>
        <Heading style={heading}>Email updated</Heading>
        <Text style={bodyText}>
          Your account email was changed successfully.
        </Text>
        <Text style={{ ...bodyText, margin: '14px 0 6px' }}>
          <span style={emailLabel}>Previous:</span>{' '}
          <span style={emailBadge}>{oldEmail}</span>
        </Text>
        <Text style={{ ...bodyText, margin: '6px 0 0' }}>
          <span style={emailLabel}>Current:</span>{' '}
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
