import type { SelectOption } from '../../lib/base/Select.svelte';
import { t } from '../../lib/i18n/index.svelte';
import type { RangePreset } from '../cells/analytics/types';
import { PRESET_MS } from './plan';
import { VIZ_KINDS } from './specs';

const PRESETS = Object.keys(PRESET_MS) as RangePreset[];

export function vizKindOptions(): SelectOption[] {
  return VIZ_KINDS.map((kind) => ({ value: kind, label: t(`viz.${kind}`) }));
}

export function rangeOptions(): SelectOption[] {
  return [{ value: '', label: t('analytics.range_global') }, ...PRESETS.map((item) => ({ value: item, label: t(`analytics.preset_${item}`) }))];
}

export function metricOptions(catalog: readonly { id: string; label?: string }[]): SelectOption[] {
  return catalog.map((entry) => ({ value: entry.id, label: entry.label || entry.id }));
}

export function measureOptions(): SelectOption[] {
  return [{ value: 'tokens', label: t('viz.measure_tokens') }, { value: 'cost', label: t('viz.measure_cost') }];
}
