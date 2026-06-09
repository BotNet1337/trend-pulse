import * as React from 'react';
import { Heading, Section, Text } from '@react-email/components';
import { EmailLayout } from '../../components/layout.js';
import { EmailPrimaryButton, safeHref } from '../../components/button.js';

void React;

export interface RenewalEmailProps {
  userName: string;
  planName: string;
  daysLeft: number | string;
  renewUrl: string;
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

const urgencyText = {
  fontSize: '15px',
  lineHeight: '26px',
  color: '#DC2626',
  fontWeight: 600 as const,
  margin: '0 0 20px',
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

export function RenewalEmail({ userName, planName, daysLeft, renewUrl }: RenewalEmailProps) {
  const days = Number(daysLeft);
  const dayLabel = days === 1 ? 'day' : 'days';

  return (
    <EmailLayout
      previewText={`Your ${planName} subscription expires in ${daysLeft} ${dayLabel} — renew now`}
      tagline="Viral content detector"
    >
      <Section style={content}>
        <Heading style={heading}>Your subscription is expiring soon</Heading>
        <Text style={bodyText}>Hi {userName},</Text>
        <Text style={urgencyText}>
          Your {planName} plan expires in {daysLeft} {dayLabel}.
        </Text>
        <Text style={bodyText}>
          Renew now to keep uninterrupted access to your watchlists, alerts, and TrendPulse
          analytics.
        </Text>
        <Section style={{ marginTop: '24px' }}>
          <EmailPrimaryButton href={renewUrl} label="Renew subscription" />
        </Section>
        <Text style={muted}>
          If you have already renewed,{' '}
          <a href={safeHref(renewUrl)} style={link}>
            check your billing status
          </a>{' '}
          in the dashboard.
        </Text>
      </Section>
    </EmailLayout>
  );
}
