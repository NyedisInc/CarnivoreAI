import type { OutboxEntry } from '../../../lib/outbox/outbox-model';
import { WAIT_FOR_TRIGGER } from '../../../lib/outbox/outbox-model';
import type { SentSend, SentTell } from '../../api/sent.svelte';
import type { ChartColumns } from '../../lib/run-chart';
import { agoWords, nextWords, runTimeWords } from '../../lib/run-chart';
import type { Mark } from './model';

export type Translate = (key: string, params?: Record<string, string | number>) => string;

export interface SentRow extends Record<string, unknown> {
  id: string;
  mark: Mark;
  what: string;
  where: string;
  session: string;
  tell: string;
  agoSeconds: number;
}

export const SENT_COLUMNS: ChartColumns = {
  all: [
    { key: 'what', headKey: 'opscenter.sent.column.what', minPx: 64, weight: 1.6, insetPx: 12 },
    { key: 'where', headKey: 'opscenter.sent.column.where', minPx: 48, weight: 1 },
    { key: 'session', headKey: 'opscenter.sent.column.session', minPx: 48, weight: 1 },
    { key: 'tell', headKey: 'opscenter.sent.column.send', minPx: 64, weight: 1.4 },
    { key: 'ago', headKey: 'opscenter.column.ago', minPx: 40, weight: 0.01, align: 'end', insetPx: 12, fit: 'ago' },
  ],
  narrow: ['what', 'tell', 'ago'],
  wideAt: 440,
  tight: ['what', 'tell', 'ago'],
  tightAt: 340,
  phone: [
    { key: 'what', headKey: '', minPx: 0, weight: 1, line: 1 },
    { key: 'ago', headKey: '', minPx: 0, weight: 0, align: 'end', line: 1 },
    { key: 'tell', headKey: '', minPx: 0, weight: 1, line: 2 },
    { key: 'session', headKey: '', minPx: 0, weight: 0, align: 'end', line: 2 },
    { key: 'where', headKey: '', minPx: 0, weight: 0, align: 'end', line: 2 },
  ],
};

const TELL_MARKS: Readonly<Record<string, Mark>> = {
  told: 'ok', read: 'ok', filed: 'ok',
  queued: 'running', waiting: 'running', held: 'running', filing: 'running',
  not_sent: 'error', gone: 'error', expired: 'error', stuck: 'error',
  swarm: 'skipped',
};

function oneLine(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(' ');
}

export function tellWords(tell: SentTell, nowS: number, t: Translate): string {
  const agent = tell.label ?? '';
  switch (tell.state) {
    case 'told':
      if (agent && tell.at !== null) return t('opscenter.sent.send.told', { agent, time: agoWords(nowS - tell.at) });
      return agent ? t('opscenter.sent.send.sent_agent', { agent }) : t('opscenter.sent.send.sent_plain');
    case 'queued':
      return t('opscenter.sent.send.queued', { wait: tell.due_at === null ? '' : runTimeWords(Math.max(0, tell.due_at - nowS) * 1000) });
    case 'held': return t('opscenter.sent.send.held', { agent });
    case 'expired': return t('opscenter.sent.send.expired', { agent });
    case 'gone': return t('opscenter.sent.send.gone', { agent });
    case 'not_sent': return t('opscenter.sent.send.not_sent', { reason: tell.reason ?? '' });
    case 'filing': return t('opscenter.sent.send.filing', { agent });
    case 'read': case 'waiting': case 'swarm': case 'filed': case 'stuck':
      return t(`opscenter.sent.send.${tell.state}`);
    default: return '';
  }
}

export function sentRows(sends: readonly SentSend[], nowS: number, t: Translate): SentRow[] {
  return sends.map((send) => ({
    id: send.key,
    mark: TELL_MARKS[send.tell.state] ?? 'none',
    what: `${t(`opscenter.sent.kind.${send.kind}`)}: ${oneLine(send.text)}`,
    where: send.item?.title || send.list_name || send.list,
    session: send.session ?? send.tell.label ?? '',
    tell: tellWords(send.tell, nowS, t),
    agoSeconds: Math.max(0, nowS - send.at),
  }));
}

export interface LocalRow {
  id: string;
  failed: boolean;
  name: string;
  where: string;
  words: string;
}

export function localRows(entries: readonly OutboxEntry[], nowMs: number, t: Translate): LocalRow[] {
  return entries.map((e) => {
    const name = `${t(`opscenter.sent.kind.${e.kind}`)}: ${oneLine(e.label.text)}`;
    const reason = e.error?.message === 'task_manager_answered' ? t('opscenter.sent.local.answered_elsewhere') : (e.error?.message ?? '');
    let words: string;
    if (e.state === 'failed') words = t('opscenter.sent.local.failed', { reason });
    else if (e.state === 'sending') words = t('opscenter.sent.local.sending');
    else if (e.next_at === WAIT_FOR_TRIGGER) words = t('opscenter.sent.local.waiting');
    else words = t('opscenter.sent.local.pending', { time: nextWords(Math.max(0, (e.next_at - nowMs) / 1000)) });
    return { id: e.id, failed: e.state === 'failed', name, where: e.label.where, words };
  });
}
