import * as React from 'react';
import { Column, Row, Section, Text } from '@react-email/components';

void React;

export interface BrandHeaderProps {
  tagline?: string;
}

// Dark aurora header band (solid #070b1d fallback)
const header = {
  backgroundColor: '#070b1d',
  background: 'linear-gradient(135deg,#070b1d 0%,#0c1228 50%,#1b2350 100%)',
  padding: '22px 36px',
};

const markCell = {
  width: '44px',
  height: '44px',
  borderRadius: '12px',
  backgroundColor: '#4f46e5',
  background: 'linear-gradient(135deg,#2563eb 0%,#7c3aed 100%)',
  textAlign: 'center' as const,
  verticalAlign: 'middle' as const,
  fontSize: '22px',
  lineHeight: '44px',
};

const nameText = {
  fontSize: '17px',
  fontWeight: 700 as const,
  color: '#ffffff',
  letterSpacing: '-0.02em',
  margin: '0',
  lineHeight: '1.2',
};

const taglineText = {
  fontSize: '12px',
  color: '#a3aecb',
  margin: '2px 0 0',
  lineHeight: '1.4',
};

export function BrandHeader({ tagline }: BrandHeaderProps) {
  return (
    <Section style={header}>
      <Row>
        <Column style={{ width: '58px', verticalAlign: 'middle' }}>
          <table
            cellPadding="0"
            cellSpacing="0"
            role="presentation"
            style={{ borderCollapse: 'collapse' as const }}
          >
            <tbody>
              <tr>
                <td style={markCell}>
                  📈
                </td>
              </tr>
            </tbody>
          </table>
        </Column>
        <Column style={{ verticalAlign: 'middle' }}>
          <Text style={nameText}>Foresignal</Text>
          {tagline ? <Text style={taglineText}>{tagline}</Text> : null}
        </Column>
      </Row>
    </Section>
  );
}
