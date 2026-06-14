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
  margin: '0',
  padding: '0',
  wordSpacing: 'normal',
  backgroundColor: '#eef1fb',
  fontFamily:
    "'Inter','Segoe UI',Roboto,'Helvetica Neue',Helvetica,Arial,sans-serif",
};

const container = {
  margin: '0 auto',
  padding: '32px 12px',
  width: '600px',
  maxWidth: '600px',
};

// Aurora accent bar (flat gradient, solid #7c3aed fallback)
const accentBar = {
  height: '5px',
  lineHeight: '5px',
  fontSize: '1px',
  backgroundColor: '#7c3aed',
  background: 'linear-gradient(90deg,#2563eb 0%,#7c3aed 50%,#22d3ee 100%)',
  borderRadius: '16px 16px 0 0',
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
          <Section style={accentBar}>&nbsp;</Section>
          <BrandHeader tagline={tagline} />
          {children}
          <EmailFooter unsubscribeUrl={unsubscribeUrl} />
        </Container>
      </Body>
    </Html>
  );
}
