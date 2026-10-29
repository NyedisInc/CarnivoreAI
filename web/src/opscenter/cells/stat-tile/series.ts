/* could not be determined */

import { history } from '../../api';
import { SPARK_BOX_PX, stats, type Figure, type Figures, type SparkBar, type StatCard } from '../../data/stats';
import { t } from '../../../lib/i18n/index.svelte';

export const PRIORITY: readonly string[] = stats.map((card) => card.id);

export function visibleCards(count: number): StatCard[] {
  const keep = new Set(PRIORITY.slice(0, Math.max(1, Math.min(PRIORITY.length, count))));
  return stats.filter((card) => keep.has(card.id));
}

export function bucket(series: readonly number[], bars: number): number[] {
  if (!series.length || bars < 1) return [];
  const means: number[] = [];
  for (let index = 0; index < bars; index += 1) {
    const from = Math.floor((index * series.length) / bars);
    const to = Math.max(from + 1, Math.floor(((index + 1) * series.length) / bars));
    const slice = series.slice(from, to);
    means.push(slice.reduce((sum, value) => sum + value, 0) / slice.length);
  }
  return means;
}

export function sparkBars(card: StatCard, bars: number): SparkBar[] {
  const series = history.series(card.key);
  const values = series.length >= bars ? bucket(series, bars) : series;
  const drawn: SparkBar[] = values.map((value) => ({
    h: Math.max(0, Math.min(SPARK_BOX_PX, value * card.unit)),
    tone: card.barTone,
  }));
  while (drawn.length < bars) drawn.push({ h: 0, tone: card.barTone });
  return drawn;
}

export function seriesFor(card: StatCard): number[] {
  return history.series(card.key);
}

export function extent(series: readonly number[]): { min: number | null; max: number | null } {
  if (!series.length) return { min: null, max: null };
  return { min: Math.min(...series), max: Math.max(...series) };
}

export interface Reading {
  text: string;
  kind: 'value' | 'dim' | 'note';
  chart: boolean;
}

const NOTE_KEYS: Readonly<Record<string, string>> = {
  probe_unavailable: 'opscenter.stat.note.probe_unavailable',
  never_probed: 'opscenter.stat.note.never_probed',
  'no-accounts': 'opscenter.stat.note.no_accounts',
  'not-reported': 'opscenter.stat.note.not_reported',
  unavailable: 'opscenter.stat.note.unavailable',
};

export function reading(figure: Figure, format: (value: number) => string): Reading {
  if (figure.value !== null) return { text: format(figure.value), kind: 'value', chart: true };
  if (figure.status === 'error') {
    return { text: figure.message || t('opscenter.value.read_failed'), kind: 'note', chart: false };
  }
  if (figure.status === 'could-not-determine') {
    return {
      text: t(NOTE_KEYS[figure.message] ?? 'opscenter.stat.note.undetermined'),
      kind: 'note',
      chart: false,
    };
  }
  const noteKey = NOTE_KEYS[figure.status];
  if (noteKey) return { text: t(noteKey), kind: 'note', chart: false };
  return { text: t('opscenter.value.undetermined'), kind: 'dim', chart: figure.status === 'loading' };
}

export function delta(card: StatCard): string | null {
  const series = history.series(card.key);
  if (series.length < 2) return null;
  const last = series[series.length - 1];
  const previous = series[series.length - 2];
  if (last === undefined || previous === undefined) return null;
  const change = Math.round(last - previous);
  if (change === 0) return null;
  return change > 0 ? `+${change}` : String(change);
}

export function resetLine(seconds: number | null): string {
  if (seconds === null) return '';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) {
    return t('opscenter.stat.resets_in_hours', {
      hours,
      minutes: String(minutes).padStart(2, '0'),
    });
  }
  return t('opscenter.stat.resets_in_minutes', { minutes });
}

export function subagentLine(figure: Figure): string {
  if (figure.value === null) return '';
  return t('opscenter.stat.subagents_running', { count: figure.value });
}

export function cardReading(card: StatCard, figures: Figures): Reading {
  if (card.id === 'running') return reading(figures.running, String);
  if (card.id === 'sessions') return reading(figures.sessions24h, String);
  if (card.id === 'projects') return reading(figures.projects, String);
  if (card.id === 'ledger') return reading(figures.ledger, (value) => `${value}%`);
  if (card.id === 'subagents') return reading(figures.subagentsRunning, String);
  if (card.id === 'alive') {
    return reading(figures.alive, (value) => (figures.total === null || figures.total === 0 ? String(value) : `${value}/${figures.total}`));
  }
  return { text: t('opscenter.value.undetermined'), kind: 'dim', chart: false };
}

export interface Secondary {
  text: string;
  meter: number | null;
}

export function secondary(card: StatCard, figures: Figures): Secondary | null {
  const { detail } = figures;
  if (card.id === 'running') {
    return figures.alive.value === null ? null : { text: t('opscenter.stat.of_alive', { total: figures.alive.value }), meter: null };
  }
  if (card.id === 'sessions') {
    if (detail.liveRows === null || detail.closed24h === null) return null;
    return { text: t('opscenter.stat.live_closed', { live: detail.liveRows, closed: detail.closed24h }), meter: null };
  }
  if (card.id === 'projects') {
    return detail.projectsWithLive === null ? null : { text: t('opscenter.stat.projects_live', { count: detail.projectsWithLive }), meter: null };
  }
  if (card.id === 'ledger') {
    if (figures.ledger.value === null) return null;
    return { text: resetLine(figures.ledgerResetSeconds), meter: Math.max(0, Math.min(100, figures.ledger.value)) };
  }
  if (card.id === 'alive') {
    if (figures.alive.value === null || !figures.total) return null;
    return {
      text: t('opscenter.stat.stopped', { count: figures.total - figures.alive.value }),
      meter: Math.round((figures.alive.value / figures.total) * 100),
    };
  }
  if (card.id === 'subagents') {
    return detail.subagentParents === null ? null : { text: t('opscenter.stat.in_sessions', { count: detail.subagentParents }), meter: null };
  }
  return null;
}
