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
  unsubscribeUrl?: string;
  children: ReactNode;
}

const body = {
  backgroundColor: '#070b1d',
  fontFamily:
    '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Ubuntu,sans-serif',
};

const container = {
  margin: '0 auto',
  padding: '40px 20px',
  maxWidth: '560px',
};

const card = {
  backgroundColor: '#0d1432',
  border: '1px solid rgba(255,255,255,0.09)',
  borderRadius: '24px',
  overflow: 'hidden' as const,
  boxShadow: '0 24px 64px rgba(0,0,0,0.6), 0 1px 0 rgba(255,255,255,0.06) inset',
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
