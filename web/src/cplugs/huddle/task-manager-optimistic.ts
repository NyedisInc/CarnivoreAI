import type { HuddleItem, TaskManagerMessage } from './huddle-model';
import { isApproved } from './huddle-model';

export type Undo = () => void;

const WAITING_TO_SEND = 'waiting_to_send';
const HELD_STATUSES = new Set(['todo']);

type Touched = Pick<HuddleItem, 'state' | 'status' | 'section' | 'needs_you' | 'needs_action' | 'thread' | 'note' | 'unread' | 'info_unread' | 'info_unseen' | 'attention_unread' | 'attention_unseen'>;

function snapshot(item: HuddleItem): Undo {
  const before: Touched = {
    state: item.state, status: item.status, section: item.section, needs_you: item.needs_you,
    needs_action: item.needs_action, thread: item.thread, note: item.note, unread: item.unread,
    info_unread: item.info_unread, info_unseen: item.info_unseen, attention_unread: item.attention_unread, attention_unseen: item.attention_unseen,
  };
  return () => Object.assign(item, before);
}

function joeChanged(item: HuddleItem): void {
  if (!HELD_STATUSES.has(item.status ?? '')) {
    item.status = WAITING_TO_SEND;
    item.section = WAITING_TO_SEND;
  }
  item.needs_you = false;
  item.needs_action = null;
}

export function applyTick(item: HuddleItem, approved: boolean): Undo {
  const undo = snapshot(item);
  item.state = approved ? 'done' : 'review';
  if (approved || isApproved(item.state) || item.status === 'done') joeChanged(item);
  return undo;
}

export function applyMarkRead(item: HuddleItem, through?: number): Undo {
  const undo = snapshot(item);
  item.thread = item.thread.map((m) => (m.unread && m.author !== 'joe' && (through === undefined || m.id <= through) ? { ...m, unread: false } : m));
  const left = item.thread.some((m) => m.unread && m.author !== 'joe');
  item.unread = left;
  if (!left) {
    item.info_unread = 0;
    item.info_unseen = false;
    item.attention_unread = 0;
    item.attention_unseen = false;
  }
  if (item.needs_action === 'read' && !left) {
    item.needs_you = false;
    item.needs_action = null;
  }
  return undo;
}

export function applyReviewCheck(item: HuddleItem, checkId: string, checked: boolean): Undo {
  const before = item.review_checks;
  item.review_checks = (before ?? []).map((c) => (c.id === checkId ? { ...c, checked, checked_by: checked ? 'joe' : null, checked_at: checked ? Date.now() / 1000 : null } : c));
  return () => { item.review_checks = before; };
}

function answered(thread: readonly TaskManagerMessage[], only?: number): TaskManagerMessage[] {
  return thread.map((m) => (m.kind === 'question' && !m.answered && (only === undefined || m.id === only) ? { ...m, answered: true } : m));
}

export function applyAnswered(item: HuddleItem, only?: number): Undo {
  const undo = snapshot(item);
  item.thread = answered(item.thread, only);
  if (!item.thread.some((m) => m.kind === 'question' && !m.answered)) joeChanged(item);
  return undo;
}

export function applyReply(item: HuddleItem, text: string, now: number = Date.now() / 1000): Undo {
  const undo = snapshot(item);
  const provisional: TaskManagerMessage = {
    id: -Math.max(1, Math.round(now * 1000)), item_id: item.id, author: 'joe', kind: 'reply', text, answered: false,
    created_at: now, seq: item.seq,
  };
  item.thread = [...answered(item.thread), provisional];
  if (item.state === 'review' || isApproved(item.state)) item.state = 'open';
  if (item.thread_count !== undefined) item.thread_count += 1;
  joeChanged(item);
  return () => {
    undo();
    if (item.thread_count !== undefined) item.thread_count -= 1;
  };
}

export function threadCount(item: Pick<HuddleItem, 'thread' | 'thread_count'>): number {
  return item.thread_count ?? item.thread.length;
}

export function mergeThread(fresh: HuddleItem, loaded: readonly TaskManagerMessage[] | null): HuddleItem {
  if (!fresh.thread_slim || !loaded) return fresh;
  const newest = new Map(fresh.thread.map((m) => [m.id, m]));
  const merged = loaded.filter((m) => m.id >= 0).map((m) => newest.get(m.id) ?? m);
  const have = new Set(merged.map((m) => m.id));
  for (const m of fresh.thread) if (!have.has(m.id)) merged.push(m);
  merged.sort((a, b) => a.id - b.id);
  return { ...fresh, thread: merged };
}
