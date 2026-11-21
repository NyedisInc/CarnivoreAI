/* does not exist yet */
import { addChart } from '../cells/analytics/state.svelte';
import { PRESETS, presetConfig } from '../viz/presets';

export const PRESET_KIND = 'analytics:preset:';

export function isFreshChartKind(kind: string): boolean {
  return kind === 'analytics:new' || kind.startsWith(PRESET_KIND);
}

export function resolveDropKind(kind: string): string {
  if (kind === 'analytics:new') return `analytics:${addChart().id}`;
  if (!kind.startsWith(PRESET_KIND)) return kind;
  const preset = PRESETS.find((one) => one.id === kind.slice(PRESET_KIND.length));
  return preset ? `analytics:${addChart(presetConfig(preset)).id}` : kind;
}
