import * as React from 'react';
import { Hr, Section, Text } from '@react-email/components';
import { safeHref } from './button.js';

void React;

const wrapper = {
  backgroundColor: '#ffffff',
  padding: '28px 36px',
  borderRadius: '0 0 16px 16px',
};

const divider = {
  borderColor: '#eef1f6',
  margin: '0 0 14px',
};

const muted = {
  color: '#94a3b8',
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
  color: '#64748b',
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
