import * as React from 'react';
import { Heading, Section, Text } from '@react-email/components';
import { EmailLayout } from '../../components/layout.js';
import { EmailPrimaryButton, safeHref } from '../../components/button.js';

void React;

export interface WelcomeEmailProps {
  userName: string;
  dashboardUrl: string;
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

const stepsLabel = {
  fontSize: '15px',
  fontWeight: 600 as const,
  color: '#0F172A',
  margin: '20px 0 8px',
};

const stepsList = {
  fontSize: '14px',
  lineHeight: '28px',
  color: '#475569',
  margin: '0',
  paddingLeft: '18px',
};

const muted = {
  fontSize: '13px',
  lineHeight: '22px',
  color: '#94A3B8',
  marginTop: '24px',
};

const link = {
  color: '#6366F1',
  textDecoration: 'none' as const,
  fontWeight: 500 as const,
};

export function WelcomeEmail({ userName, dashboardUrl }: WelcomeEmailProps) {
  return (
    <EmailLayout
      previewText={`Welcome to TrendPulse, ${userName}`}
      tagline="Viral content detector"
    >
      <Section style={content}>
        <Heading style={heading}>Welcome, {userName}!</Heading>
        <Text style={bodyText}>
          Your TrendPulse account is ready. Start tracking viral content from Telegram right now.
        </Text>
        <Text style={stepsLabel}>Get started in 3 steps:</Text>
        <ol style={stepsList}>
          <li>Add topics to your watchlist</li>
          <li>Connect Telegram channels</li>
          <li>Receive alerts when trends emerge</li>
        </ol>
        <Section style={{ marginTop: '24px' }}>
          <EmailPrimaryButton href={dashboardUrl} label="Go to dashboard" />
        </Section>
        <Text style={muted}>
          Need help?{' '}
          <a href={safeHref(dashboardUrl)} style={link}>
            Visit settings
          </a>{' '}
          to manage your account.
        </Text>
      </Section>
    </EmailLayout>
  );
}
