'use client';

import type { CSSProperties } from 'react';
import type { SubtitlePanelProps } from './types';

const panelStyle: CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  padding: '8px 12px',
  borderRadius: 12,
  border: '1px solid rgba(124, 151, 255, 0.24)',
  background: 'rgba(250, 252, 255, 0.94)',
  color: '#27406B',
  fontSize: 13,
  lineHeight: 1.6,
  textAlign: 'left',
  boxShadow: '0 10px 30px rgba(79, 108, 191, 0.08)',
  backdropFilter: 'blur(8px)',
};

export function SubtitlePanel({ subtitle, className, style, children }: SubtitlePanelProps) {
  const content = children ?? subtitle;
  if (!content) {
    return null;
  }

  return (
    <div
      className={['avatar-ui-kit__subtitle', className].filter(Boolean).join(' ')}
      style={{ ...panelStyle, ...style }}
      aria-live="polite"
    >
      {content}
    </div>
  );
}
