import { t } from '../../../lib/i18n/index.svelte';

export function formatValue(value: number | null, unit: string): string {
  if (value === null) return t('analytics.unknown');
  if (unit.startsWith('nano_usd')) return `est. $${(value / 1_000_000_000).toFixed(4)}${unit.slice('nano_usd'.length)}`;
  if (unit === 'fraction') return `${(value * 100).toFixed(1)}%`;
  if (unit === 'percent') return `${value.toFixed(1)}%`;
  return new Intl.NumberFormat().format(value);
}

export function localValue(iso: string): string {
  const date = new Date(iso);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export function clockLabel(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  const clock = when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return when.toDateString() === new Date().toDateString() ? clock : `${when.toLocaleDateString([], { month: 'short', day: 'numeric' }).toLowerCase()} ${clock}`;
}
