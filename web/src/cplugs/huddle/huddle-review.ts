import { statusOf } from './huddle-status';
import { mdPlain } from './task-manager-markdown';
import type { HuddleItem, TaskManagerMessage } from './huddle-model';

export const ACTIONS = ['tick', 'push', 'answer', 'read', 'none', 'unstick'] as const;
export type ReviewAction = (typeof ACTIONS)[number];

export function actionOf(value: unknown): ReviewAction | null {
  return (ACTIONS as readonly unknown[]).includes(value) ? (value as ReviewAction) : null;
}

const STATUS_ECHO_ACTIONS: readonly ReviewAction[] = ['answer', 'read'];

export function isStatusEcho(value: unknown): boolean {
  const action = actionOf(value);
  return action !== null && STATUS_ECHO_ACTIONS.includes(action);
}

export interface ReviewBlock {
  action: ReviewAction;
  summary: string;
  hasMore: boolean;
  description: string;
  where: string;
  link: string;
}

export const SUMMARY_MAX = 140;

const LINE_MARKER = /^(?:#{1,6}|[-*+]|\d+[.)]|>)\s+/;

export function summarize(text: string, stored: string = '', max: number = SUMMARY_MAX): { summary: string; more: boolean } {
  if (stored) {
    const own = stored.replace(/\s+/g, ' ');
    return { summary: own, more: text !== '' && text !== own };
  }
  const lines = text.split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('```'));
  if (!lines.length) return { summary: '', more: false };
  const plain = mdPlain(lines[0].replace(LINE_MARKER, '')).replace(/\s+/g, ' ').trim();
  const end = plain.search(/[.!?](?:\s|$)/);
  let summary = end >= 0 ? plain.slice(0, end + 1) : plain;
  let more = lines.length > 1 || summary.length < plain.length;
  if (summary.length > max) {
    summary = `${summary.slice(0, max - 1).trimEnd()}\u2026`;
    more = true;
  }
  return { summary, more };
}

/* the review card */
export interface ReviewAnswer {
  id: number;
  summary: string;
  hasMore: boolean;
  text: string;
}

export function reviewAnswerOf(item: HuddleItem): ReviewAnswer | null {
  const thread: TaskManagerMessage[] = item.thread ?? [];
  const asked = new Set(thread.filter((m) => m.author === 'joe' && m.kind === 'reply' && m.answers_to === undefined).map((m) => m.id));
  const answer = [...thread].reverse().find((m) => m.author === 'claude' && m.kind === 'answer' && m.quote?.id != null && asked.has(m.quote.id));
  if (!answer) return null;
  const text = answer.text.trim();
  const { summary, more } = summarize(text);
  return { id: answer.id, summary, hasMore: more, text };
}

export function reviewOf(item: HuddleItem): ReviewBlock | null {
  if (statusOf(item) !== 'review') return null;
  const description = (item.review_description ?? '').trim();
  const { summary, more } = summarize(description, (item.review_summary ?? '').trim());
  const block = {
    action: actionOf(item.review_action) ?? 'tick',
    summary,
    hasMore: more,
    description,
    where: (item.review_where ?? '').trim(),
    link: (item.review_link ?? '').trim(),
  };
  return block.description || block.where || block.link ? block : null;
}

export interface LinkTarget {
  kind: 'app' | 'external';
  href: string;
  hash: string | null;
}

export function linkTarget(link: string, here: Pick<Location, 'origin' | 'pathname'>): LinkTarget | null {
  let url: URL;
  try {
    url = new URL(link, here.origin);
  } catch {
    return null;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  if (link.startsWith('//') || link.includes('\\')) return null;
  if (url.origin !== here.origin) return { kind: 'external', href: url.href, hash: null };
  return { kind: 'app', href: `${url.pathname}${url.search}${url.hash}`, hash: url.pathname === here.pathname && url.hash ? url.hash : null };
}

export function followHash(hash: string, win: Window = window): void {
  if (win.location.hash === hash) win.dispatchEvent(new HashChangeEvent('hashchange'));
  else win.location.hash = hash;
}
