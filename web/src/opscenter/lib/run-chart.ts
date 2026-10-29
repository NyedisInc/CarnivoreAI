import { t } from '../../lib/i18n/index.svelte';
import type { ColumnSpec } from '../engine/types';
import { compact, elapsed, relative } from './format';

export type FitKind = 'runTime' | 'ago' | 'next' | 'count';

export interface ChartColumn extends ColumnSpec {
  fit?: FitKind;
}

export interface ChartColumns {
  all: readonly ChartColumn[];
  narrow: readonly string[];
  wideAt: number;
  tight: readonly string[];
  tightAt: number;
  phone: readonly ColumnSpec[];
}

const WIDEST_SAMPLES: Readonly<Record<FitKind, readonly number[]>> = {
  runTime: [999, 59_900, 3_599_000, 359_940_000],
  ago: [59, 3_599, 86_399, 8_639_999],
  next: [3_599, 86_399, 8_639_999],
  count: [9_999, 99_900, 9_990_000],
};

export function widestChars(kind: FitKind): number {
  const words: Record<FitKind, (value: number) => string> = {
    runTime: runTimeWords,
    ago: agoWords,
    next: nextWords,
    count: (value) => compact(value),
  };
  const extra = kind === 'next' ? [t('opscenter.chart.paused').length] : [];
  return Math.max(...extra, ...WIDEST_SAMPLES[kind].map((value) => words[kind](value).length));
}

function sized(column: ChartColumn): ColumnSpec {
  const { fit, ...spec } = column;
  return fit ? { ...spec, minCh: widestChars(fit) } : spec;
}

export function columnsFor(table: ChartColumns, width: number, phone: boolean): ColumnSpec[] {
  if (phone) return [...table.phone];
  if (width >= table.wideAt) return table.all.map(sized);
  const keep = width < table.tightAt ? table.tight : table.narrow;
  return table.all.filter((column) => keep.includes(column.key)).map(sized);
}

const MS_PER_SECOND = 1000;
const MS_PER_MINUTE = 60_000;
const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_DAY = 86_400;
const SECONDS_PER_HOUR = 3_600;

export function runTimeWords(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms) || ms < 0) return '';
  if (ms < MS_PER_SECOND) return t('opscenter.time.run_ms', { count: Math.round(ms) });
  if (ms < MS_PER_MINUTE) return t('opscenter.time.run_seconds', { count: Math.round(ms / 100) / 10 });
  return elapsed(ms / MS_PER_SECOND);
}

export function agoWords(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '';
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < SECONDS_PER_MINUTE) return t('opscenter.time.ago_seconds', { count: whole });
  return relative(whole / SECONDS_PER_MINUTE);
}

export function nextWords(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '';
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < SECONDS_PER_DAY) return t('opscenter.cell.developer.in', { time: elapsed(whole) });
  const hours = String(Math.floor((whole % SECONDS_PER_DAY) / SECONDS_PER_HOUR)).padStart(2, '0');
  const time = t('opscenter.time.until_days', { days: Math.floor(whole / SECONDS_PER_DAY), hours });
  return t('opscenter.cell.developer.in', { time });
}
