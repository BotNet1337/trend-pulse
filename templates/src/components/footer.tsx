import * as React from 'react';
import { Hr, Section, Text } from '@react-email/components';
import { safeHref } from './button.js';

void React;

const wrapper = {
  padding: '0 36px 28px',
};

const divider = {
  borderColor: 'rgba(255,255,255,0.08)',
  margin: '0 0 20px',
};

const muted = {
  color: '#4e5a78',
  fontSize: '11px',
  lineHeight: '18px',
  margin: '0',
  letterSpacing: '0.01em',
};

const copyright = {
  ...muted,
  marginTop: '3px',
};

const unsubscribeLink = {
  color: '#67e8f9',
  textDecoration: 'underline' as const,
};

export interface EmailFooterProps {
  unsubscribeUrl?: string;
}

export function EmailFooter({ unsubscribeUrl }: EmailFooterProps = {}) {
  return (
    <Section style={wrapper}>
      <Hr style={divider} />
      <Text style={muted}>
        Foresignal &middot; You received this email because of activity on your
        account.
      </Text>
      {unsubscribeUrl ? (
        <Text style={copyright}>
          <a href={safeHref(unsubscribeUrl)} style={unsubscribeLink}>
            Unsubscribe
          </a>{' '}
          from these emails. Transactional emails (verification, password
          reset, billing) are not affected.
        </Text>
      ) : null}
      <Text style={copyright}>&copy; 2026 Foresignal</Text>
    </Section>
  );
}
