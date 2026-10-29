import { formatSi } from '../../viz/format';
import { t } from '../../../lib/i18n/index.svelte';

export function displayHeadline(value: number | null, unit: string): string {
  if (value === null) return t('analytics.unknown');
  if (unit.startsWith('nano_usd')) return `$${new Intl.NumberFormat(undefined, { maximumFractionDigits: value >= 1_000_000_000 ? 2 : 4 }).format(value / 1_000_000_000)}`;
  if (unit === 'fraction') return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value * 100)}%`;
  if (unit === 'percent') return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value)}%`;
  return formatSi(value);
}

export function cacheHitRate(read: number | null, fresh: number | null, written: number | null): number | null {
  if (read === null || fresh === null || written === null) return null;
  const total = read + fresh + written;
  return total > 0 ? read / total : null;
}
