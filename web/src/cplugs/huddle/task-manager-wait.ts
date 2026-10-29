import { dueLabel, type DueWords } from './task-manager-schedule';
import type { HuddleItem } from './huddle-model';

export interface WaitLine {
  on: string;
  check: string;
  extended: string;
  /* owner has been asked */
  asked: boolean;
  hold: boolean;
}

export interface WaitWords {
  t: (key: string, params?: Record<string, string | number>) => string;
  due: DueWords;
}

export function waitLine(item: HuddleItem, now: Date, words: WaitWords, locale?: string): WaitLine {
  const wait = item.wait;
  const none = { on: '', check: '', extended: '', asked: false, hold: false };
  if (item.state !== 'waiting') return none;
  const hold = (item.blockers ?? []).find((b) => b.kind === 'children');
  if (!wait && hold) return { ...none, on: words.t('cplug.huddle.wait.forks', { count: hold.holding ?? 0 }), hold: true };
  if (!wait) return none;
  return {
    on: words.t('cplug.huddle.wait.on', { what: wait.waiting_on, by: dueLabel(wait.expect_by, now, words.due, locale) }),
    check: wait.check_kind ? words.t('cplug.huddle.wait.check', { kind: words.t(`cplug.huddle.wait.check_kind.${wait.check_kind}`) }) : '',
    extended: wait.extended && wait.extend_reason ? words.t('cplug.huddle.wait.extended', { reason: wait.extend_reason }) : '',
    asked: wait.status === 'escalated',
    hold: false,
  };
}

export interface WaitChip {
  label: string;
  overdue: boolean;
  hold: boolean;
}

export function waitChip(item: HuddleItem, now: Date, words: WaitWords, locale?: string): WaitChip | null {
  if (item.state !== 'waiting') return null;
  const wait = item.wait;
  if (!wait) {
    const hold = (item.blockers ?? []).find((b) => b.kind === 'children');
    return hold ? { label: words.t('cplug.huddle.wait.chip_forks'), overdue: false, hold: true } : null;
  }
  return {
    label: words.t('cplug.huddle.wait.chip', { by: dueLabel(wait.expect_by, now, words.due, locale) }),
    overdue: wait.expect_by * 1000 < now.getTime(),
    hold: false,
  };
}
