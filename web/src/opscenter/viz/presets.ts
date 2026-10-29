import type { ChartConfig, ChartSeries, RangePreset, Viz } from '../cells/analytics/types';
import { t } from '../../lib/i18n/index.svelte';

export type GalleryCategory = 'live' | 'flow' | 'agents' | 'change' | 'system';
export const GALLERY_CATEGORIES: readonly GalleryCategory[] = ['live', 'flow', 'agents', 'change', 'system'];
export type GallerySize = 'tile' | 'panel' | 'full';

export interface Preset {
  id: string;
  category: GalleryCategory;
  viz: Viz;
  options: Record<string, unknown>;
  series: ChartSeries[];
  display: ChartConfig['display'];
  range?: RangePreset;
  size: GallerySize;
}

const LINE: ChartConfig['display'] = { type: 'line', legend: true };
const STACKED: ChartConfig['display'] = { type: 'area', stacked: true, legend: true };

export const PRESETS: readonly Preset[] = [
  { id: 'vitals', category: 'live', viz: 'vitals', options: {}, series: [{ metric: 'total_tokens' }], display: LINE, size: 'panel' },
  { id: 'hot_agents', category: 'live', viz: 'hot', options: {}, series: [{ metric: 'total_tokens' }], display: LINE, size: 'panel' },
  { id: 'event_ticker', category: 'live', viz: 'events', options: {}, series: [{ metric: 'total_tokens' }], display: LINE, size: 'panel' },
  { id: 'fleet_rack', category: 'live', viz: 'fleet', options: {}, series: [{ metric: 'total_tokens' }], display: LINE, size: 'panel' },
  { id: 'quota_runway', category: 'live', viz: 'runway', options: {}, series: [{ metric: 'quota_utilization', group_by: 'account_id' }], display: LINE, range: '6h', size: 'panel' },
  { id: 'waiting_on_you', category: 'live', viz: 'kpi', options: { compare_prior: true }, series: [{ metric: 'waiting_seconds' }], display: LINE, size: 'tile' },
  { id: 'sessions_started', category: 'live', viz: 'kpi', options: { compare_prior: true }, series: [{ metric: 'starts' }], display: LINE, size: 'tile' },
  { id: 'working_time', category: 'live', viz: 'timeline', options: {}, series: [{ metric: 'working_seconds' }], display: LINE, size: 'panel' },
  { id: 'working_rhythm', category: 'live', viz: 'heat', options: {}, series: [{ metric: 'working_seconds' }], display: LINE, range: '7d', size: 'full' },

  { id: 'token_history', category: 'flow', viz: 'timeline', options: {}, series: [{ metric: 'total_tokens' }], display: LINE, size: 'panel' },
  { id: 'kpi_tokens', category: 'flow', viz: 'kpi', options: { compare_prior: true }, series: [{ metric: 'total_tokens' }], display: LINE, size: 'tile' },
  { id: 'kpi_cost', category: 'flow', viz: 'kpi', options: { compare_prior: true }, series: [{ metric: 'estimated_cost_nano_usd' }], display: LINE, size: 'tile' },
  { id: 'cost_by_model', category: 'flow', viz: 'timeline', options: {}, series: [{ metric: 'estimated_cost_nano_usd', group_by: 'model' }], display: { type: 'bar', stacked: true, legend: true }, size: 'panel' },
  { id: 'tokens_by_account', category: 'flow', viz: 'timeline', options: {}, series: [{ metric: 'total_tokens', group_by: 'account_id' }], display: STACKED, size: 'panel' },
  { id: 'top_projects', category: 'flow', viz: 'leaderboard', options: { top_n: 8 }, series: [{ metric: 'total_tokens', operation: 'ranking', group_by: 'project' }], display: LINE, range: '7d', size: 'panel' },
  { id: 'top_models_cost', category: 'flow', viz: 'leaderboard', options: { top_n: 8 }, series: [{ metric: 'estimated_cost_nano_usd', operation: 'ranking', group_by: 'model' }], display: LINE, range: '7d', size: 'panel' },
  { id: 'spend_treemap', category: 'flow', viz: 'treemap', options: { measure: 'cost' }, series: [{ metric: 'estimated_cost_nano_usd' }], display: LINE, range: '7d', size: 'full' },
  { id: 'token_treemap', category: 'flow', viz: 'treemap', options: { measure: 'tokens' }, series: [{ metric: 'total_tokens' }], display: LINE, range: '7d', size: 'full' },
  { id: 'spend_flow', category: 'flow', viz: 'flow', options: { measure: 'cost' }, series: [{ metric: 'estimated_cost_nano_usd' }], display: LINE, range: '7d', size: 'full' },
  { id: 'token_flow', category: 'flow', viz: 'flow', options: { measure: 'tokens' }, series: [{ metric: 'total_tokens' }], display: LINE, range: '7d', size: 'full' },
  { id: 'token_rhythm', category: 'flow', viz: 'heat', options: {}, series: [{ metric: 'total_tokens' }], display: LINE, range: '7d', size: 'full' },

  { id: 'subagent_share', category: 'agents', viz: 'timeline', options: {}, series: [{ metric: 'total_tokens', group_by: 'subagent_type' }], display: STACKED, size: 'panel' },
  { id: 'subagent_time', category: 'agents', viz: 'timeline', options: {}, series: [{ metric: 'subagent_seconds' }], display: LINE, size: 'panel' },
  { id: 'agent_swimlanes', category: 'agents', viz: 'swimlanes', options: {}, series: [{ metric: 'working_seconds' }], display: LINE, range: '6h', size: 'full' },
  { id: 'outlier_hunter', category: 'agents', viz: 'scatter', options: {}, series: [{ metric: 'estimated_cost_nano_usd' }], display: LINE, range: '7d', size: 'panel' },
  { id: 'tool_calls', category: 'agents', viz: 'leaderboard', options: { top_n: 10 }, series: [{ metric: 'tool_calls', operation: 'ranking', group_by: 'key' }], display: LINE, range: '7d', size: 'panel' },
  { id: 'top_agents', category: 'agents', viz: 'agents', options: {}, series: [{ metric: 'total_tokens', operation: 'timeline', group_by: 'conversation_id' }], display: LINE, range: '24h', size: 'panel' },

  { id: 'tokens_vs_prior', category: 'change', viz: 'timeline', options: {}, series: [{ metric: 'total_tokens', operation: 'comparison' }], display: LINE, size: 'panel' },
  { id: 'change_impact', category: 'change', viz: 'impact', options: { annotation_id: '', metric: 'estimated_cost_nano_usd', days: 7 }, series: [{ metric: 'estimated_cost_nano_usd' }], display: LINE, size: 'panel' },
  { id: 'cost_vs_prior', category: 'change', viz: 'timeline', options: {}, series: [{ metric: 'estimated_cost_nano_usd', operation: 'comparison' }], display: LINE, size: 'panel' },

  { id: 'quota_by_account', category: 'system', viz: 'timeline', options: {}, series: [{ metric: 'quota_utilization', group_by: 'account_id' }], display: LINE, size: 'panel' },
  { id: 'cache_hit', category: 'system', viz: 'timeline', options: {}, series: [{ metric: 'cache_read_tokens' }, { metric: 'input_tokens' }, { metric: 'cache_write_tokens' }], display: STACKED, size: 'panel' },
  { id: 'stop_reasons', category: 'system', viz: 'leaderboard', options: { top_n: 6 }, series: [{ metric: 'stop_reasons', operation: 'ranking', group_by: 'key' }], display: LINE, range: '7d', size: 'panel' },
  { id: 'pack_machines', category: 'live', viz: 'pack', options: {}, series: [{ metric: 'total_tokens' }], display: LINE, size: 'panel' },
  { id: 'collector_health', category: 'system', viz: 'health', options: {}, series: [{ metric: 'total_tokens' }], display: LINE, size: 'panel' },
  { id: 'compactions', category: 'system', viz: 'timeline', options: {}, series: [{ metric: 'compactions' }], display: LINE, size: 'panel' },
];

export const presetTitleKey = (preset: Preset): string => `gallery.preset.${preset.id}`;
export const presetNoteKey = (preset: Preset): string => `gallery.preset.${preset.id}_note`;

export function presetConfig(preset: Preset): ChartConfig {
  return {
    id: '', revision: 0, title: t(presetTitleKey(preset)), enabled: true, viz: preset.viz,
    options: structuredClone(preset.options), series: structuredClone(preset.series), filters: {},
    range: { mode: 'global', ...(preset.range ? { preset: preset.range } : {}) },
    display: structuredClone(preset.display),
  };
}
