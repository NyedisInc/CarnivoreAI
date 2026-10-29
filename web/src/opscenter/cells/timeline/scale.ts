import { timeMs } from './model';
import type { Gap, SessionTimeline } from './types';

export const SQUEEZE_MIN_MS = 20 * 60_000;
export const BREAK_PX = 18;
export const BREAK_SHARE_MAX = 0.4;

const STEPS_MIN: readonly number[] = [1, 2, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1440, 2880, 10080];
const MIN_MS = 60_000;

export interface Segment {
  kind: 'time' | 'break';
  t0: number;
  t1: number;
  x0: number;
  x1: number;
}

export interface Scale {
  t0: number;
  t1: number;
  segments: Segment[];
  x: (ms: number) => number;
}

export interface Tick {
  key: string;
  x: number;
  label: string;
  kind: 'start' | 'now' | 'break' | 'day' | 'time';
  anchor: 'start' | 'middle' | 'end';
}

export function sleepBreaks(gaps: readonly Gap[], t0: number, t1: number, nowMs: number): Array<[number, number]> {
  const spans = gaps
    .map((gap): [number, number] | null => {
      const start = timeMs(gap.start);
      const end = gap.end === null ? nowMs : timeMs(gap.end);
      if (start === null || end === null) return null;
      const from = Math.max(t0, start);
      const to = Math.min(t1, end);
      return to - from >= SQUEEZE_MIN_MS ? [from, to] : null;
    })
    .filter((span): span is [number, number] => span !== null)
    .sort((a, b) => a[0] - b[0]);
  const merged: Array<[number, number]> = [];
  for (const span of spans) {
    const last = merged[merged.length - 1];
    if (last && span[0] <= last[1]) last[1] = Math.max(last[1], span[1]);
    else merged.push([span[0], span[1]]);
  }
  return merged;
}

function affordable(breaks: Array<[number, number]>, plotPx: number): Array<[number, number]> {
  const most = Math.floor((plotPx * BREAK_SHARE_MAX) / BREAK_PX);
  if (breaks.length <= most) return breaks;
  return [...breaks].sort((a, b) => b[1] - b[0] - (a[1] - a[0])).slice(0, Math.max(0, most)).sort((a, b) => a[0] - b[0]);
}

export function buildScale(data: SessionTimeline, plotPx: number, squeeze: boolean): Scale | null {
  const starts = data.bars.map((b) => timeMs(b.started_at));
  const ends = data.bars.map((b) => timeMs(b.ended_at));
  if (data.bars.length === 0 || starts.some((s) => s === null) || ends.some((e) => e === null)) return null;
  const nowMs = timeMs(data.now) ?? 0;
  const t0 = Math.min(...(starts as number[]));
  const t1 = Math.max(...(ends as number[]), nowMs);
  if (t1 <= t0) return null;
  const breaks = squeeze ? affordable(sleepBreaks(data.gaps, t0, t1, nowMs), plotPx) : [];
  const pieces: Array<Omit<Segment, 'x0' | 'x1'>> = [];
  let cursor = t0;
  for (const [from, to] of breaks) {
    if (from > cursor) pieces.push({ kind: 'time', t0: cursor, t1: from });
    pieces.push({ kind: 'break', t0: from, t1: to });
    cursor = to;
  }
  if (cursor < t1) pieces.push({ kind: 'time', t0: cursor, t1 });
  const awakeMs = pieces.filter((p) => p.kind === 'time').reduce((sum, p) => sum + (p.t1 - p.t0), 0);
  const awakePx = Math.max(0, plotPx - breaks.length * BREAK_PX);
  let x = 0;
  const segments: Segment[] = pieces.map((p) => {
    const width = p.kind === 'break' ? BREAK_PX : awakeMs > 0 ? ((p.t1 - p.t0) / awakeMs) * awakePx : 0;
    const seg = { ...p, x0: x, x1: x + width };
    x += width;
    return seg;
  });
  const map = (ms: number): number => {
    const at = Math.min(t1, Math.max(t0, ms));
    const seg = segments.find((s) => at >= s.t0 && at <= s.t1) ?? segments[segments.length - 1]!;
    return seg.t1 === seg.t0 ? seg.x0 : seg.x0 + ((at - seg.t0) / (seg.t1 - seg.t0)) * (seg.x1 - seg.x0);
  };
  return { t0, t1, segments, x: map };
}

export function clockOf(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function dayOf(ms: number): string {
  return new Date(ms).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toLowerCase();
}

export function stampOf(ms: number): string {
  return `${dayOf(ms)} ${clockOf(ms)}`;
}

export function spanWords(ms: number): string {
  const min = Math.max(1, Math.round(ms / MIN_MS));
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return min % 60 === 0 ? `${h}h` : `${h}h ${min % 60}m`;
  const d = Math.floor(h / 24);
  return h % 24 === 0 ? `${d}d` : `${d}d ${h % 24}h`;
}

export const V_LINE_PX = 12;
export const V_TICK_GAP_PX = 36;
export const V_LABEL_PAD_PX = 4;

function edges(tick: Tick): [number, number] {
  const w = tick.label.split('\n').length * V_LINE_PX;
  if (tick.anchor === 'start') return [tick.x, tick.x + w];
  if (tick.anchor === 'end') return [tick.x - w, tick.x];
  return [tick.x - w / 2, tick.x + w / 2];
}

export function rulerTicks(scale: Scale, plotPx: number): Tick[] {
  const join = '\n';
  const gapPx = V_TICK_GAP_PX;
  const padPx = V_LABEL_PAD_PX;
  const wanted: Tick[] = [
    { key: 'start', x: 0, label: `${dayOf(scale.t0)}${join}${clockOf(scale.t0)}`, kind: 'start', anchor: 'start' },
    { key: 'now', x: plotPx, label: 'now', kind: 'now', anchor: 'end' },
  ];
  let lastDay = dayOf(scale.t0);
  for (const seg of scale.segments) {
    if (seg.kind === 'break') {
      wanted.push({ key: `break:${seg.t0}`, x: (seg.x0 + seg.x1) / 2, label: spanWords(seg.t1 - seg.t0), kind: 'break', anchor: 'middle' });
      continue;
    }
    const minutes = (seg.t1 - seg.t0) / MIN_MS;
    if (minutes <= 0) continue;
    const ppm = (seg.x1 - seg.x0) / minutes;
    const step = STEPS_MIN.find((s) => s * ppm >= gapPx) ?? STEPS_MIN[STEPS_MIN.length - 1]!;
    const offset = new Date(seg.t0).getTimezoneOffset();
    const localMin = (ms: number): number => Math.floor(ms / MIN_MS) - offset;
    for (let m = Math.ceil(localMin(seg.t0) / step) * step; m <= localMin(seg.t1); m += step) {
      const ms = (m + offset) * MIN_MS;
      if (ms <= seg.t0 || ms >= seg.t1) continue;
      const day = dayOf(ms);
      const newDay = day !== lastDay;
      lastDay = day;
      const label = m % 1440 === 0 ? day : newDay ? `${day}${join}${clockOf(ms)}` : clockOf(ms);
      wanted.push({ key: `t:${ms}`, x: scale.x(ms), label, kind: newDay ? 'day' : 'time', anchor: 'middle' });
    }
  }
  const rank: Record<Tick['kind'], number> = { start: 0, now: 1, day: 2, break: 3, time: 4 };
  const placed: Tick[] = [];
  for (const tick of [...wanted].sort((a, b) => rank[a.kind] - rank[b.kind] || a.x - b.x)) {
    const [l, r] = edges(tick);
    if (l < -1 || r > plotPx + 1) continue;
    if (placed.some((p) => { const [pl, pr] = edges(p); return l < pr + padPx && r > pl - padPx; })) continue;
    placed.push(tick);
  }
  return placed.sort((a, b) => a.x - b.x);
}
