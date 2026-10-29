import type { CrosstalkThread, HistoryScope, ThreadParticipant } from '../../../lib/crosstalk/history/history-model';
import { t } from '../../../lib/i18n/index.svelte';
import type { ThreadMessage } from '../../../lib/crosstalk/history/conversations.svelte';

export type { ThreadMessage };

export const NEW_WINDOW_S = 60 * 60;
export const MAX_MARKS = 300;
export const RUN_GAP_S = 5 * 60;
export const SPLIT_MIN_WIDTH = 560;
export const STACK_MIN_HEIGHT = 320;
export const STACK_SPLIT_DEFAULT = 0.4;
export const STACK_SPLIT_MIN = 0.2;
export const STACK_SPLIT_MAX = 0.75;
export const STACK_SPLIT_STEP = 0.05;
export const LIST_SHARE = 0.42;
export const LIST_MAX_WIDTH = 420;
export const CAPTION_FULL_WIDTH = 400;
export const COUNT_MIN_WIDTH = 360;
export const QUOTE_CHARS = 48;

export interface SeenMarks {
  since: number;
  threads: Record<string, number>;
}

export const NO_MARKS: SeenMarks = { since: 0, threads: {} };

export function isSeenMarks(value: unknown): value is SeenMarks {
  if (!value || typeof value !== 'object') return false;
  const marks = value as Partial<SeenMarks>;
  if (typeof marks.since !== 'number' || !marks.threads || typeof marks.threads !== 'object') return false;
  return Object.values(marks.threads).every((at) => typeof at === 'number');
}

export function direction(thread: CrosstalkThread): { from: ThreadParticipant; to: ThreadParticipant } {
  const sides = thread.participants;
  const from = sides.find((side) => side.key === thread.last_sender_key) ?? sides[0]!;
  const to = sides.find((side) => side.key !== from.key) ?? from;
  return { from, to };
}

export function isNew(thread: CrosstalkThread, marks: SeenMarks, baseline: number): boolean {
  const mark = marks.threads[thread.thread] ?? (marks.since || baseline);
  return thread.last_at > mark;
}

export function markSeen(marks: SeenMarks, thread: string, at: number, baseline: number): SeenMarks {
  const threads = { ...marks.threads, [thread]: at };
  const kept = Object.entries(threads).sort((a, b) => b[1] - a[1]).slice(0, MAX_MARKS);
  return { since: marks.since || baseline, threads: Object.fromEntries(kept) };
}

export function markAllSeen(nowS: number): SeenMarks {
  return { since: nowS, threads: {} };
}

export function ageText(epochS: number, nowMs: number): string {
  const seconds = Math.max(0, Math.round(nowMs / 1000 - epochS));
  if (seconds < 60) return t('crosstalk.widget.age_now');
  if (seconds < 3600) return t('crosstalk.widget.age_minutes', { n: Math.floor(seconds / 60) });
  if (seconds < 86400) return t('crosstalk.widget.age_hours', { n: Math.floor(seconds / 3600) });
  if (seconds < 7 * 86400) return t('crosstalk.widget.age_days', { n: Math.floor(seconds / 86400) });
  return shortDate(epochS);
}

export function shortDate(epochS: number): string {
  const date = new Date(epochS * 1000);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' }).toLowerCase();
}

export function fullTime(epochS: number): string {
  const date = new Date(epochS * 1000);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

export function clockText(epochS: number): string {
  const date = new Date(epochS * 1000);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function dayLabel(epochS: number, nowMs: number): string {
  const day = (ms: number): number => new Date(ms).setHours(0, 0, 0, 0);
  const diff = Math.round((day(nowMs) - day(epochS * 1000)) / 86400000);
  if (diff === 0) return t('crosstalk.widget.day_today');
  if (diff === 1) return t('crosstalk.widget.day_yesterday');
  return shortDate(epochS);
}

export interface Delivery {
  word: string;
  bad: boolean;
}

export function delivery(status: string, to: string): Delivery | null {
  switch (status) {
    case 'delivered': return null;
    case 'queued': return { word: t('crosstalk.widget.delivery_queued'), bad: false };
    case 'held': return { word: t('crosstalk.widget.delivery_held', { to }), bad: false };
    case 'delivering': return { word: t('crosstalk.widget.delivery_delivering'), bad: false };
    case 'failed': return { word: t('crosstalk.widget.delivery_failed'), bad: true };
    case 'expired': return { word: t('crosstalk.widget.delivery_expired'), bad: true };
    default: return { word: status, bad: false };
  }
}

export function scopeCaption(scope: HistoryScope, subject: string): { label: string; subject: string } {
  if (scope === 'all') return { label: t('crosstalk.widget.scope_all'), subject: '' };
  return { label: t(scope === 'project' ? 'crosstalk.widget.scope_project' : 'crosstalk.widget.scope_session'), subject };
}

export function countText(shown: number, fresh: number, more: boolean, short = false): string {
  if (short) return fresh > 0 ? t('crosstalk.widget.count_new', { n: fresh }) : `${shown}${more ? '+' : ''}`;
  const total = t(shown === 1 && !more ? 'crosstalk.widget.count_one' : 'crosstalk.widget.count_many', { n: `${shown}${more ? '+' : ''}` });
  return fresh > 0 ? t('crosstalk.widget.count_with_new', { total, fresh }) : total;
}

export function emptyText(scope: HistoryScope, subject: string): string {
  if (scope === 'session') return t('crosstalk.widget.empty_session', { name: subject || t('crosstalk.widget.this_session') });
  if (scope === 'project') return t(subject ? 'crosstalk.widget.empty_project_named' : 'crosstalk.widget.empty_project', { name: subject });
  return t('crosstalk.widget.empty_all');
}

export function loadingText(scope: HistoryScope, subject: string): string {
  if (scope === 'all' || !subject) return t(scope === 'all' ? 'crosstalk.widget.loading_all' : 'crosstalk.widget.loading');
  return t(scope === 'project' ? 'crosstalk.widget.loading_project' : 'crosstalk.widget.loading_session', { name: subject });
}

export type Layout = 'side' | 'stack' | 'drill';

export function layoutFor(width: number, height: number): Layout {
  if (width >= SPLIT_MIN_WIDTH) return 'side';
  return height >= STACK_MIN_HEIGHT ? 'stack' : 'drill';
}

export function clampSplit(n: number): number {
  return Math.min(STACK_SPLIT_MAX, Math.max(STACK_SPLIT_MIN, n));
}

export function isSplit(value: unknown): value is number {
  return typeof value === 'number' && value >= STACK_SPLIT_MIN && value <= STACK_SPLIT_MAX;
}

export function splitStep(key: string, current: number): number | null {
  const round = (n: number): number => Math.round(clampSplit(n) * 100) / 100;
  switch (key) {
    case 'ArrowUp': return round(current - STACK_SPLIT_STEP);
    case 'ArrowDown': return round(current + STACK_SPLIT_STEP);
    case 'Home': return STACK_SPLIT_MIN;
    case 'End': return STACK_SPLIT_MAX;
    case 'Enter': return STACK_SPLIT_DEFAULT;
    default: return null;
  }
}

export type TranscriptItem =
  | { kind: 'day'; key: string; label: string }
  | { kind: 'notice'; key: string; text: string; at: number }
  | {
    kind: 'message';
    key: string;
    message: ThreadMessage;
    head: boolean;
    side: number;
    from: string;
    to: string;
    replyTo: string;
    asksReply: boolean;
    delivery: Delivery | null;
  };

function sentBy(message: ThreadMessage, side: ThreadParticipant): boolean {
  return (!!message.sender_key && message.sender_key === side.key) || message.sender_id === side.id
    || (!!side.session_uuid && message.sender_uuid === side.session_uuid);
}

export function quote(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length > QUOTE_CHARS ? `${flat.slice(0, QUOTE_CHARS - 1)}...` : flat;
}

export function transcript(messages: readonly ThreadMessage[], sides: readonly ThreadParticipant[], nowMs: number): TranscriptItem[] {
  const items: TranscriptItem[] = [];
  const byId = new Map(messages.map((m) => [m.id, m]));
  let lastDay = '';
  let previous: ThreadMessage | null = null;
  messages.forEach((message, at) => {
    const day = dayLabel(message.created_at, nowMs);
    if (day !== lastDay) {
      items.push({ kind: 'day', key: `day-${message.id}`, label: day });
      lastDay = day;
      previous = null;
    }
    if (message.source === 'system') {
      items.push({ kind: 'notice', key: message.id, text: message.text, at: message.created_at });
      previous = null;
      return;
    }
    const side = Math.max(0, sides.findIndex((s) => sentBy(message, s)));
    const prior: ThreadMessage | null = previous;
    const sameRun = prior !== null && sameSender(prior, message) && message.created_at - prior.created_at < RUN_GAP_S;
    const parent = message.in_reply_to ? byId.get(message.in_reply_to) : undefined;
    const replyTo = !message.in_reply_to || (prior !== null && prior.id === message.in_reply_to)
      ? '' : parent ? quote(parent.text) : t('crosstalk.widget.reply_earlier');
    const answered = messages.slice(at + 1).some((later) => later.source !== 'system' && !sameSender(later, message));
    const to = message.receiver_name || message.receiver_id;
    items.push({
      kind: 'message', key: message.id, message, head: !sameRun || replyTo !== '', side,
      from: message.sender_name || message.sender_id, to,
      replyTo, asksReply: Boolean(message.expect_reply) && !answered, delivery: delivery(message.status, to),
    });
    previous = message;
  });
  return items;
}

function sameSender(a: ThreadMessage, b: ThreadMessage): boolean {
  if (a.sender_key && b.sender_key) return a.sender_key === b.sender_key;
  return a.sender_id === b.sender_id;
}

export function stepIndex(key: string, index: number, count: number, page: number): number | null {
  if (count === 0) return null;
  const clamp = (n: number): number => Math.min(count - 1, Math.max(0, n));
  switch (key) {
    case 'ArrowDown': return clamp(index + 1);
    case 'ArrowUp': return clamp(index - 1);
    case 'Home': return 0;
    case 'End': return count - 1;
    case 'PageDown': return clamp(index + Math.max(1, page));
    case 'PageUp': return clamp(index - Math.max(1, page));
    default: return null;
  }
}
