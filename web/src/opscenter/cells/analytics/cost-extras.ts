import { displayHeadline } from './headline';
import { describeDelta, type DeltaDirection } from '../../viz/format';
import { t } from '../../../lib/i18n/index.svelte';

export function spanLabel(ms: number): string {
  const hours = Math.max(1, Math.round(ms / 3600_000));
  return hours < 48 ? `${hours}h` : `${Math.round(hours / 24)}d`;
}

export function costLine(current: number | null, prior: number | null, unit: string, ms: number): { change: { text: string; direction: DeltaDirection } | null; average: string | null } {
  const delta = describeDelta(current, prior);
  const hours = ms / 3600_000;
  return {
    change: delta.direction === 'none' ? null : { direction: delta.direction, text: t('analytics.cost_vs_prior', { change: delta.text, span: spanLabel(ms) }) },
    average: current === null || hours <= 0 ? null : t('analytics.cost_per_hour', { value: displayHeadline(current / hours, unit) }),
  };
}
