import * as React from 'react';
import { Heading, Section, Text } from '@react-email/components';
import { EmailLayout } from '../../components/layout.js';
import { EmailPrimaryButton } from '../../components/button.js';

void React;

export interface DigestItemProps {
  /** Sanitized topic label (no URLs/handles — compliance §7). */
  topic: string;
  /** Score formatted as a string on the backend boundary (e.g. "92.5"). */
  score: string;
  /** Curated pack slug; null for manually created watchlists. */
  packSlug?: string | null;
}

export interface WeeklyDigestEmailProps {
  userName: string;
  items: DigestItemProps[];
  dashboardUrl: string;
  /** Unsubscribe URL (TASK-069) — required on lifecycle emails. */
  unsubscribeUrl: string;
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

// Aurora-cycled left borders (blue / violet / cyan) — border-left is email-safe.
const accentColors = ['#2563eb', '#7c3aed', '#0891b2'] as const;

const itemRowBase = {
  padding: '12px 16px',
  backgroundColor: '#f8fafc',
  borderRadius: '12px',
  marginBottom: '8px',
};

const itemTopic = {
  fontSize: '14px',
  fontWeight: 600 as const,
  color: '#0f172a',
  margin: '0 0 2px',
  lineHeight: '22px',
};

const itemMeta = {
  fontSize: '12px',
  color: '#94a3b8',
  margin: '0',
  lineHeight: '18px',
};

export function WeeklyDigestEmail({
  userName,
  items,
  dashboardUrl,
  unsubscribeUrl,
}: WeeklyDigestEmailProps) {
  return (
    <EmailLayout
      previewText="Your top signals of the week on Foresignal"
      tagline="Viral content detector"
      unsubscribeUrl={unsubscribeUrl}
    >
      <Section style={content}>
        <Heading style={heading}>Your week on Foresignal</Heading>
        <Text style={bodyText}>Hi {userName},</Text>
        <Text style={bodyText}>
          Here are the top signals your packs caught over the last 7 days:
        </Text>
        {items.map((item, index) => (
          <Section
            key={`${item.topic}-${index}`}
            style={{
              ...itemRowBase,
              borderLeft: `3px solid ${accentColors[index % accentColors.length]}`,
            }}
          >
            <Text style={itemTopic}>{item.topic}</Text>
            <Text style={itemMeta}>
              Score {item.score}
              {item.packSlug ? ` · Pack: ${item.packSlug}` : ''}
            </Text>
          </Section>
        ))}
        <Section style={{ marginTop: '24px' }}>
          <EmailPrimaryButton href={dashboardUrl} label="Open Foresignal" />
        </Section>
      </Section>
    </EmailLayout>
  );
}
