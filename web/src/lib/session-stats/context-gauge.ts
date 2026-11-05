import { scaleStep } from '../../../../client/js/labels/usage-panel.js';

export interface ContextGauge {
  pct: number;
  scale: number;
}

export function contextGauge(raw: unknown): ContextGauge | null {
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return null;
  const pct = Math.min(100, Math.max(0, raw));
  const scale = scaleStep(pct) as number | null;
  return scale === null ? null : { pct, scale };
}

export function contextPercentSpoken(raw: unknown): number | null {
  const gauge = contextGauge(raw);
  return gauge === null ? null : Math.round(gauge.pct);
}

export function contextUsedPct(usedTokens: number | null | undefined, windowTokens: number | null | undefined): number | null {
  if (typeof usedTokens !== 'number' || typeof windowTokens !== 'number') return null;
  if (!Number.isFinite(usedTokens) || !Number.isFinite(windowTokens) || windowTokens <= 0) return null;
  return Math.min(100, Math.max(0, (usedTokens / windowTokens) * 100));
}

export function modelShortName(model: unknown): string {
  return typeof model === 'string' ? model.trim().replace(/^claude-/, '') : '';
}
