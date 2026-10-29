import { t } from '../../lib/i18n/index.svelte';

function digits(value: number, max: number, min = 0): string {
  return new Intl.NumberFormat(undefined, { minimumFractionDigits: min, maximumFractionDigits: max }).format(value);
}

export function formatSi(value: number): string {
  const abs = Math.abs(value);
  const steps: [number, string][] = [[1e12, 'viz.si_t'], [1e9, 'viz.si_b'], [1e6, 'viz.si_m'], [1e3, 'viz.si_k']];
  for (const [size, key] of steps) if (abs >= size) return t(key, { value: digits(value / size, abs / size >= 100 ? 0 : abs / size >= 10 ? 1 : 2) });
  return digits(value, abs < 10 && !Number.isInteger(value) ? 2 : 1);
}

export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const d = Math.floor(total / 86400), h = Math.floor(total % 86400 / 3600), m = Math.floor(total % 3600 / 60), s = total % 60;
  if (d) return h ? t('viz.dur_dh', { d, h }) : t('viz.dur_d', { d });
  if (h) return m ? t('viz.dur_hm', { h, m }) : t('viz.dur_h', { h });
  if (m) return s ? t('viz.dur_ms', { m, s }) : t('viz.dur_m', { m });
  return t('viz.dur_s', { s });
}

function suffixOf(unit: string): string {
  const at = unit.indexOf('/');
  const tail = at < 0 ? '' : unit.slice(at + 1);
  return tail === 'second' ? t('viz.per_second') : tail === 'conversation' ? t('viz.per_conversation') : '';
}

export function formatMetric(value: number | null, unit: string): { text: string; unit: string } {
  if (value === null || !Number.isFinite(value)) return { text: t('viz.no_data'), unit: '' };
  const base = unit.split('/')[0] ?? unit;
  const tail = suffixOf(unit);
  if (base === 'nano_usd') return { text: t('viz.usd', { value: digits(value / 1e9, Math.abs(value) >= 1e10 ? 0 : Math.abs(value) >= 1e9 ? 2 : 4, Math.abs(value) >= 1e10 ? 0 : 2) }), unit: tail };
  if (base === 'percent') return { text: t('viz.percent', { value: digits(value, 1) }), unit: tail };
  if (base === 'fraction') return { text: t('viz.percent', { value: digits(value * 100, 1) }), unit: tail };
  if (base === 'seconds' && !tail) return { text: formatDuration(value), unit: '' };
  return { text: formatSi(value), unit: `${base === 'tokens' ? '' : base}${tail}`.trim() };
}

export type DeltaDirection = 'up' | 'down' | 'flat' | 'none';

export function describeDelta(current: number | null, prior: number | null): { direction: DeltaDirection; text: string } {
  if (current === null || prior === null || prior === 0) return { direction: 'none', text: t('viz.delta_none') };
  const change = (current - prior) / Math.abs(prior) * 100;
  const shown = digits(Math.abs(change), 1);
  if (shown === '0') return { direction: 'flat', text: t('viz.delta_flat') };
  const percent = t('viz.percent', { value: shown });
  return change > 0 ? { direction: 'up', text: t('viz.delta_up', { value: percent }) } : { direction: 'down', text: t('viz.delta_down', { value: percent }) };
}
