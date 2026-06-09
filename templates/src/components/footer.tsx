import * as React from 'react';
import { Hr, Section, Text } from '@react-email/components';

void React;

const wrapper = {
  padding: '0 36px 28px',
};

const divider = {
  borderColor: '#F1F5F9',
  margin: '0 0 20px',
};

const muted = {
  color: '#CBD5E1',
  fontSize: '11px',
  lineHeight: '18px',
  margin: '0',
  letterSpacing: '0.01em',
};

const copyright = {
  ...muted,
  marginTop: '3px',
};

export function EmailFooter() {
  return (
    <Section style={wrapper}>
      <Hr style={divider} />
      <Text style={muted}>
        TrendPulse &middot; You received this email because of activity on your
        account.
      </Text>
      <Text style={copyright}>&copy; 2026 TrendPulse</Text>
    </Section>
  );
}
