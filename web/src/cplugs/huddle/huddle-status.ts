import { hasOpenQuestion, type HuddleItem } from './huddle-model';

export type TaskManagerStatus = 'open' | 'question' | 'working' | 'review' | 'waiting' | 'scheduled' | 'todo' | 'done';

const STATUSES: readonly TaskManagerStatus[] = ['open', 'question', 'working', 'review', 'waiting', 'scheduled', 'todo', 'done'];

export const STATUS_COLOR: Readonly<Record<TaskManagerStatus, string>> = Object.freeze({
  open: 'var(--oc-line-rule)',
  question: 'var(--oc-yellow-bright)',
  working: 'var(--oc-green)',
  review: 'var(--oc-cyan)',
  waiting: 'var(--oc-violet)',
  scheduled: 'var(--oc-scheduled)',
  todo: 'var(--oc-text-muted)',
  done: 'var(--oc-green-dim)',
});

export const STATUS_ICON: Readonly<Record<TaskManagerStatus, string>> = Object.freeze({
  open: 'status-idle',
  question: 'status-question',
  working: 'status-working',
  review: 'status-review',
  waiting: 'status-install',
  scheduled: 'status-scheduled',
  todo: 'status-back-burner',
  done: 'check',
});

export function statusIconColor(status: TaskManagerStatus): string {
  return status === 'open' ? 'var(--oc-text-dim)' : STATUS_COLOR[status];
}

export function statusOf(item: HuddleItem): TaskManagerStatus {
  if ((item.status as string | undefined) === 'waiting_to_send') return 'open';
  if (item.status && (STATUSES as readonly string[]).includes(item.status)) return item.status as TaskManagerStatus;
  if (item.state === 'done') return 'done';
  if (hasOpenQuestion(item)) return 'question';
  return item.state === 'review' ? 'review' : 'open';
}

export function statusKey(status: TaskManagerStatus): string {
  return `cplug.huddle.status.${status}`;
}
