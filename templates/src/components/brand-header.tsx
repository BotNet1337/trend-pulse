import * as React from 'react';
import { Column, Row, Section, Text } from '@react-email/components';

void React;

export interface BrandHeaderProps {
  tagline?: string;
}

const header = {
  padding: '24px 36px',
  borderBottom: '1px solid rgba(255,255,255,0.08)',
};

const markCell = {
  width: '44px',
  height: '44px',
  borderRadius: '14px',
  backgroundColor: '#2563eb',
  background: 'linear-gradient(140deg, #2563eb 0%, #7c3aed 60%, #a855f7 100%)',
  textAlign: 'center' as const,
  verticalAlign: 'middle' as const,
  boxShadow: '0 4px 16px rgba(37,99,235,0.35)',
  fontSize: '22px',
  lineHeight: '44px',
};

const nameText = {
  fontSize: '17px',
  fontWeight: 700 as const,
  color: '#eaeefb',
  letterSpacing: '-0.02em',
  margin: '0',
  lineHeight: '1.2',
};

const taglineText = {
  fontSize: '12px',
  color: '#8994b8',
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
                  📡
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
