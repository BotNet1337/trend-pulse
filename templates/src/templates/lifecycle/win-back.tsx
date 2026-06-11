import * as React from 'react';
import { Heading, Section, Text } from '@react-email/components';
import { EmailLayout } from '../../components/layout.js';
import { EmailPrimaryButton } from '../../components/button.js';

void React;

export interface WinBackEmailProps {
  userName: string;
  watchlistsUrl: string;
  /** Unsubscribe URL (TASK-069) — required on lifecycle emails. */
  unsubscribeUrl: string;
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
  marginTop: '24px',
};

export function WinBackEmail({ userName, watchlistsUrl, unsubscribeUrl }: WinBackEmailProps) {
  return (
    <EmailLayout
      previewText="Your Foresignal packs have been quiet lately"
      tagline="Viral content detector"
      unsubscribeUrl={unsubscribeUrl}
    >
      <Section style={content}>
        <Heading style={heading}>Your packs have been quiet</Heading>
        <Text style={bodyText}>Hi {userName},</Text>
        <Text style={bodyText}>
          We have not delivered any signals to you in the last two weeks. Your watchlists may be
          too narrow, or the thresholds too strict.
        </Text>
        <Text style={bodyText}>
          Review your packs and thresholds, or check what is trending right now — one tweak is
          usually enough to get the signal flow going again.
        </Text>
        <Section style={{ marginTop: '24px' }}>
          <EmailPrimaryButton href={watchlistsUrl} label="Review my packs" />
        </Section>
        <Text style={muted}>
          Foresignal alerts you the moment content goes viral — but only for the topics you track.
        </Text>
      </Section>
    </EmailLayout>
  );
}
