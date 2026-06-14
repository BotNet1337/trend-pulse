import * as React from 'react';
import { Heading, Section, Text } from '@react-email/components';
import { EmailLayout } from '../../components/layout.js';
import { EmailPrimaryButton } from '../../components/button.js';

void React;

export interface VerifyEmailProps {
  userName: string;
  verifyUrl: string;
  expiresAt: string;
}

const content = { padding: '32px 36px 0' };

const heading = {
  fontSize: '24px',
  fontWeight: 700 as const,
  color: '#eaeefb',
  letterSpacing: '-0.03em',
  margin: '0 0 14px',
  lineHeight: '1.2',
};

const bodyText = {
  fontSize: '15px',
  lineHeight: '26px',
  color: '#8994b8',
  margin: '0 0 10px',
};

const muted = {
  fontSize: '13px',
  lineHeight: '22px',
  color: '#4e5a78',
};

export function VerifyEmail({
  userName,
  verifyUrl,
  expiresAt,
}: VerifyEmailProps) {
  return (
    <EmailLayout
      previewText="Verify your email for Foresignal"
      tagline="Email verification"
    >
      <Section style={content}>
        <Heading style={heading}>Verify your email</Heading>
        <Text style={bodyText}>
          Hi {userName}, confirm your address to finish setting up your Foresignal
          account.
        </Text>
        <Section style={{ marginTop: '24px' }}>
          <EmailPrimaryButton href={verifyUrl} label="Verify email" />
        </Section>
        <Text style={{ ...muted, marginTop: '20px' }}>
          This link expires {expiresAt}.
        </Text>
        <Text style={{ ...muted, marginTop: '16px' }}>
          Didn&apos;t create an account? Safely ignore this.
        </Text>
      </Section>
    </EmailLayout>
  );
}
