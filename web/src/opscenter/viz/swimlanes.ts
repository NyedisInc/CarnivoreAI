import { parseServerTime } from '../lib/format';

export interface LaneSeries { key: string; label?: string; filter_value?: string | null; points: readonly { time: string; value: number | null }[] }

export type LaneState = 'working' | 'waiting' | 'idle';

export interface LaneBlock { start: number; end: number; state: LaneState; subagents: number }
export interface Lane {
  key: string;
  conversationId: string;
  label: string;
  blocks: LaneBlock[];
}

const FALLBACK_BUCKET_MS = 60_000;

export function laneModel(
  working: readonly LaneSeries[], waiting: readonly LaneSeries[], subagent: readonly LaneSeries[],
  nameOf: (conversationId: string) => string | null,
): Lane[] {
  const valueAt = (list: readonly LaneSeries[], key: string, index: number): number | null =>
    list.find((item) => item.key === key)?.points[index]?.value ?? null;
  return working.filter((series) => series.key !== 'other').map((series) => {
    const times = series.points.map((point) => parseServerTime(point.time));
    const step = times.length > 1 ? Math.max(1, (times[1] as number) - (times[0] as number)) : FALLBACK_BUCKET_MS;
    const blocks: LaneBlock[] = [];
    series.points.forEach((point, index) => {
      const w = point.value;
      const q = valueAt(waiting, series.key, index);
      const s = valueAt(subagent, series.key, index);
      const start = times[index] as number;
      if (!Number.isFinite(start) || (w === null && q === null && s === null)) return;
      const state: LaneState = (w ?? 0) > 0 ? 'working' : (q ?? 0) > 0 ? 'waiting' : 'idle';
      blocks.push({ start, end: start + step, state, subagents: Math.min(1, (s ?? 0) / (step / 1000)) });
    });
    const id = series.filter_value ?? '';
    return { key: series.key, conversationId: id, label: (id && nameOf(id)) || series.label || series.key, blocks };
  });
}
