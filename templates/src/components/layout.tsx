import * as React from 'react';
import {
  Body,
  Container,
  Head,
  Html,
  Preview,
  Section,
} from '@react-email/components';
import type { ReactNode } from 'react';
import { BrandHeader } from './brand-header.js';
import { EmailFooter } from './footer.js';

void React;

export interface EmailLayoutProps {
  previewText: string;
  tagline?: string;
  /** Optional unsubscribe URL (TASK-069) — forwarded to the footer link. */
  unsubscribeUrl?: string;
  children: ReactNode;
}

const body = {
  backgroundColor: '#F5F3FF',
  background:
    'linear-gradient(160deg, #EDE9FE 0%, #F5F3FF 30%, #FAF5FF 60%, #F0F4FF 100%)',
  fontFamily:
    '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Ubuntu,sans-serif',
};

const container = {
  margin: '0 auto',
  padding: '40px 20px',
  maxWidth: '560px',
};

const card = {
  backgroundColor: '#FFFFFF',
  border: '1px solid #E2E8F0',
  borderRadius: '24px',
  overflow: 'hidden' as const,
  boxShadow: '0 8px 32px rgba(0,0,0,0.06), 0 1px 4px rgba(0,0,0,0.04)',
};

export function EmailLayout({
  previewText,
  tagline,
  unsubscribeUrl,
  children,
}: EmailLayoutProps) {
  return (
    <Html lang="en">
      <Head />
      <Preview>{previewText}</Preview>
      <Body style={body}>
        <Container style={container}>
          <Section style={card}>
            <BrandHeader tagline={tagline} />
            {children}
            <EmailFooter unsubscribeUrl={unsubscribeUrl} />
          </Section>
        </Container>
      </Body>
    </Html>
  );
}
