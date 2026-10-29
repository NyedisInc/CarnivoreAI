import { t } from '../../lib/i18n/index.svelte';

export type EmptyTopic = 'tokens' | 'cost' | 'activity' | 'waiting' | 'starts' | 'subagents' | 'quota' | 'ranking' | 'conversations'
  | 'live' | 'vitals' | 'events' | 'accounts' | 'chart';

export function emptyTopic(metric: string | undefined, ranking = false): EmptyTopic {
  if (ranking) return 'ranking';
  const id = metric ?? '';
  if (id.includes('cost')) return 'cost';
  if (id.includes('quota')) return 'quota';
  if (id.includes('token')) return 'tokens';
  if (id.includes('waiting')) return 'waiting';
  if (id === 'starts') return 'starts';
  if (id.includes('subagent')) return 'subagents';
  if (/seconds|agents|completions/.test(id)) return 'activity';
  return 'chart';
}

export function emptyLine(topic: EmptyTopic): string {
  return t(`viz.empty_state.${topic}`);
}

export function isBlank(value: unknown): boolean {
  return typeof value !== 'number' || !Number.isFinite(value) || value === 0;
}

interface PointLike { value: number | null }

export function seriesBlank(results: readonly { series: readonly { points: readonly PointLike[] }[] }[]): boolean {
  return results.every((result) => result.series.every((series) => series.points.every((point) => isBlank(point.value))));
}
