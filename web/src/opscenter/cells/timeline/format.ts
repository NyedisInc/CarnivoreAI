import { t } from '../../../lib/i18n/index.svelte';
import type { ActivityRun, Bar, Mark } from './types';

const RESTORE_REASONS: readonly string[] = ['kill', 'remove', 'sleep', 'restart', 'backfill', 'save'];

export function when(iso: string | null | undefined): string {
  const at = iso ? new Date(iso) : null;
  if (!at || Number.isNaN(at.getTime())) return '';
  return at.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function beganWord(bar: Bar): string {
  return t(`opscenter.cell.timeline.began.${bar.began?.kind ?? 'start'}`);
}

export function kindWord(mark: Mark): string {
  return t(`opscenter.cell.timeline.kind.${mark.kind}`);
}

export function tokensWord(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return String(n);
}

export function markTitle(mark: Mark): string {
  if (mark.kind === 'bookmark') return mark.label || mark.snippet || kindWord(mark);
  if (mark.kind === 'compact') {
    return mark.pre_tokens !== null ? t('opscenter.cell.timeline.compact.dropped', { tokens: tokensWord(mark.pre_tokens) }) : t('opscenter.cell.timeline.compact.plain');
  }
  if (mark.kind === 'restore') {
    const known = mark.reason !== null && RESTORE_REASONS.includes(mark.reason) ? mark.reason : 'unknown';
    const reason = mark.failsafe ? t('opscenter.cell.timeline.restore.failsafe') : t(`opscenter.cell.timeline.restore.reason.${known}`);
    return mark.turns !== null ? `${reason}, ${t('opscenter.cell.timeline.restore.turns', { count: mark.turns })}` : reason;
  }
  return kindWord(mark);
}

export function busyMinutes(seconds: number | null | undefined): number {
  const s = seconds ?? 0;
  return s > 0 ? Math.max(1, Math.round(s / 60)) : 0;
}

export function runTitle(run: ActivityRun): string {
  const span = { from: when(run.start), to: when(run.end) };
  return run.state === 'busy'
    ? t('opscenter.cell.timeline.band.busy', { minutes: busyMinutes(run.busy_seconds), ...span })
    : t('opscenter.cell.timeline.band.idle', span);
}
