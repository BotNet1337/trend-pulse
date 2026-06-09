import * as React from 'react';
import { Heading, Section, Text } from '@react-email/components';
import { EmailLayout } from '../../components/layout.js';
import { EmailPrimaryButton } from '../../components/button.js';

void React;

export interface ResetPasswordEmailProps {
  userName: string;
  resetUrl: string;
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

const muted = {
  fontSize: '13px',
  lineHeight: '22px',
  color: '#94A3B8',
};

const infoBox = {
  fontSize: '13px',
  lineHeight: '22px',
  color: '#64748B',
  backgroundColor: '#F8FAFC',
  padding: '14px 20px',
  borderRadius: '14px',
  border: '1px solid #F1F5F9',
  marginTop: '24px',
};

export function ResetPasswordEmail({
  userName,
  resetUrl,
  expiresAt,
}: ResetPasswordEmailProps) {
  return (
    <EmailLayout previewText="Reset your TrendPulse password" tagline="Security">
      <Section style={content}>
        <Heading style={heading}>Password reset</Heading>
        <Text style={bodyText}>
          Hi {userName}, we received a request to reset your password.
        </Text>
        <Section style={{ marginTop: '24px' }}>
          <EmailPrimaryButton href={resetUrl} label="Reset password" />
        </Section>
        <Text style={{ ...muted, marginTop: '20px' }}>
          Expires {expiresAt}.
        </Text>
        <Text style={infoBox}>
          If you did not request this, no action is needed. Never share this link
          with anyone.
        </Text>
      </Section>
    </EmailLayout>
  );
}
