import * as React from 'react';
import { Heading, Section, Text } from '@react-email/components';
import { EmailLayout } from '../../components/layout.js';
import { EmailPrimaryButton, safeHref } from '../../components/button.js';

void React;

export interface UnderpaidEmailProps {
  userName: string;
  planName: string;
  /** Remaining balance in USD; null/undefined when unknown — the sum is omitted. */
  amountDue?: number | string | null;
  payUrl: string;
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

const amountText = {
  fontSize: '15px',
  lineHeight: '26px',
  color: '#dc2626',
  fontWeight: 600 as const,
  margin: '0 0 20px',
};

const muted = {
  fontSize: '13px',
  lineHeight: '22px',
  color: '#94a3b8',
  marginTop: '24px',
};

const link = {
  color: '#4f46e5',
  textDecoration: 'none' as const,
  fontWeight: 500 as const,
};

export function UnderpaidEmail({ userName, planName, amountDue, payUrl }: UnderpaidEmailProps) {
  const hasAmount = amountDue !== null && amountDue !== undefined && `${amountDue}` !== '';

  return (
    <EmailLayout
      previewText={`Your ${planName} payment is incomplete — finish it to activate your plan`}
      tagline="Viral content detector"
    >
      <Section style={content}>
        <Heading style={heading}>Your payment is incomplete</Heading>
        <Text style={bodyText}>Hi {userName},</Text>
        <Text style={bodyText}>
          We received your payment for the {planName} plan, but the amount was less than the
          invoice total, so the plan is not active yet.
        </Text>
        {hasAmount ? (
          <Text style={amountText}>Remaining balance: ${amountDue}.</Text>
        ) : (
          <Text style={amountText}>Please complete the remaining payment.</Text>
        )}
        <Text style={bodyText}>
          Send the remaining amount on the same payment page — your plan activates automatically
          as soon as the full amount is confirmed.
        </Text>
        <Section style={{ marginTop: '24px' }}>
          <EmailPrimaryButton href={payUrl} label="Complete payment" />
        </Section>
        <Text style={muted}>
          Already sent the rest? Crypto confirmations can take a little while —{' '}
          <a href={safeHref(payUrl)} style={link}>
            check the payment status
          </a>{' '}
          on the payment page.
        </Text>
      </Section>
    </EmailLayout>
  );
}
