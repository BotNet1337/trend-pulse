import * as React from 'react';
import { Heading, Section, Text } from '@react-email/components';
import { EmailLayout } from '../../components/layout.js';
import { EmailPrimaryButton, safeHref } from '../../components/button.js';

void React;

export interface WelcomeEmailProps {
  userName: string;
  dashboardUrl: string;
  /** Optional unsubscribe URL (TASK-069) — welcome is a lifecycle email. */
  unsubscribeUrl?: string;
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

const stepsLabel = {
  fontSize: '15px',
  fontWeight: 600 as const,
  color: '#0f172a',
  lineHeight: '26px',
  margin: '20px 0 8px',
};

const stepCell = {
  fontFamily:
    "'Inter','Segoe UI',Roboto,Helvetica,Arial,sans-serif",
  fontSize: '14px',
  lineHeight: '28px',
  color: '#475569',
  verticalAlign: 'middle' as const,
};

const spacerCell = {
  width: '12px',
  fontSize: '1px',
};

const muted = {
  fontSize: '13px',
  lineHeight: '22px',
  color: '#94a3b8',
  margin: '24px 0 0',
};

const link = {
  color: '#4f46e5',
  textDecoration: 'none' as const,
  fontWeight: 500 as const,
};

export function WelcomeEmail({ userName, dashboardUrl, unsubscribeUrl }: WelcomeEmailProps) {
  return (
    <EmailLayout
      previewText={`Welcome to Foresignal, ${userName}`}
      tagline="Viral content detector"
      unsubscribeUrl={unsubscribeUrl}
    >
      <Section style={content}>
        <Heading style={heading}>Welcome, {userName}!</Heading>
        <Text style={bodyText}>
          Your Foresignal account is ready. Start tracking viral content from Telegram right now.
        </Text>
        <Text style={stepsLabel}>Get started in 3 steps:</Text>

        {/* Numbered aurora chips (blue / violet / cyan) — table-based, email-safe */}
        <table
          role="presentation"
          width="100%"
          cellPadding="0"
          cellSpacing="0"
          style={{ borderCollapse: 'collapse' as const }}
        >
          <tbody>
            <tr>
              <td
                width="24"
                height="24"
                align="center"
                style={{
                  width: '24px',
                  height: '24px',
                  borderRadius: '999px',
                  backgroundColor: '#eef2ff',
                  fontSize: '12px',
                  fontWeight: 700,
                  lineHeight: '24px',
                  color: '#4f46e5',
                  textAlign: 'center',
                  verticalAlign: 'middle',
                }}
              >
                1
              </td>
              <td style={spacerCell}>&nbsp;</td>
              <td style={stepCell}>Add topics to your watchlist</td>
            </tr>
            <tr>
              <td colSpan={3} style={{ height: '8px', fontSize: '1px', lineHeight: '8px' }}>
                &nbsp;
              </td>
            </tr>
            <tr>
              <td
                width="24"
                height="24"
                align="center"
                style={{
                  width: '24px',
                  height: '24px',
                  borderRadius: '999px',
                  backgroundColor: '#f3eeff',
                  fontSize: '12px',
                  fontWeight: 700,
                  lineHeight: '24px',
                  color: '#7c3aed',
                  textAlign: 'center',
                  verticalAlign: 'middle',
                }}
              >
                2
              </td>
              <td style={spacerCell}>&nbsp;</td>
              <td style={stepCell}>Connect Telegram channels</td>
            </tr>
            <tr>
              <td colSpan={3} style={{ height: '8px', fontSize: '1px', lineHeight: '8px' }}>
                &nbsp;
              </td>
            </tr>
            <tr>
              <td
                width="24"
                height="24"
                align="center"
                style={{
                  width: '24px',
                  height: '24px',
                  borderRadius: '999px',
                  backgroundColor: '#e6fbff',
                  fontSize: '12px',
                  fontWeight: 700,
                  lineHeight: '24px',
                  color: '#0891b2',
                  textAlign: 'center',
                  verticalAlign: 'middle',
                }}
              >
                3
              </td>
              <td style={spacerCell}>&nbsp;</td>
              <td style={stepCell}>Receive alerts when trends emerge</td>
            </tr>
          </tbody>
        </table>

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
