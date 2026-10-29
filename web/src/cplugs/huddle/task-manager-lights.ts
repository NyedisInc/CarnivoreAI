import type { HuddleItem } from './huddle-model';

export type TaskManagerStripeSignal = 'attention' | 'unread' | 'info' | null;

export const SIGNAL_LABEL: Readonly<Record<'attention' | 'unread' | 'info', string>> = Object.freeze({
  attention: 'cplug.huddle.row.attention',
  unread: 'cplug.huddle.row.unread',
  info: 'cplug.huddle.row.info',
});

export const ATTENTION_STRIPE = 'var(--oc-cyan)';

export function stripeSignal(item: Pick<HuddleItem, 'unread' | 'attention_unseen' | 'info_unseen'>): TaskManagerStripeSignal {
  if (item.attention_unseen) return 'attention';
  if (item.unread) return 'unread';
  return item.info_unseen ? 'info' : null;
}

export function stripeColor(statusColor: string, signal: TaskManagerStripeSignal): string {
  return signal === 'attention' ? ATTENTION_STRIPE : statusColor;
}

export function needsSeen(item: Pick<HuddleItem, 'unread'>): boolean {
  return !!item.unread;
}
