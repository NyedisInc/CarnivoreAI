import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
import { statusKey, statusOf, type TaskManagerStatus } from '../../../cplugs/huddle/huddle-status';
import { isStatusEcho, reviewOf } from '../../../cplugs/huddle/huddle-review';
import { rowFeed, rowQuestionPick } from '../../../cplugs/huddle/task-manager-posts';
import { ageNow, clip, elapsed, isStale, type ProgressLine } from '../../../cplugs/huddle/huddle-progress';
import type { WaitLine } from '../../../cplugs/huddle/task-manager-wait';

export interface Mk2Row { labelKey: string; value: string }

export interface Mk2ActionData { statusKey: string | null; rows: Mk2Row[] }

const REAL_STATUS: ReadonlySet<TaskManagerStatus> = new Set<TaskManagerStatus>(['waiting', 'todo']);

export interface Mk2StatusLine { worker: string; text: string; stale: boolean }

export function statusLinesOf(lines: readonly ProgressLine[], sinceMs: number, words: { t: (key: string, params?: Record<string, string | number>) => string }): Mk2StatusLine[] {
  return lines.map((line) => {
    const stale = isStale(line, sinceMs);
    const age = elapsed(ageNow(line, sinceMs));
    const who = lines.length > 1 || line.worker !== 'main' ? ` ${line.worker}` : '';
    const head = `${words.t(`cplug.huddle.progress.phase.${line.phase}`)}${who}`;
    const note = line.note ? `: ${clip(line.note, 200)}` : '';
    return { worker: line.worker, text: `${head}${note}, ${stale ? words.t('cplug.huddle.progress.stale', { time: age }) : age}`, stale };
  });
}

export function actionableIdOf(item: HuddleItem): number | null {
  const feed = rowFeed(item);
  const question = rowQuestionPick(feed).shown;
  if (question !== null && question !== undefined) return question;
  if (reviewOf(item)) return null;
  return feed.at(-1)?.id ?? null;
}

export function actionDataOf(item: HuddleItem, wait?: WaitLine): Mk2ActionData {
  const rows: Mk2Row[] = [];
  const review = reviewOf(item);
  if (item.needs_action && !isStatusEcho(item.needs_action)) rows.push({ labelKey: 'opscenter.cell.task_manager_mk2.tab.needs', value: item.needs_action });
  const waitText = wait?.on ? [wait.on, wait.check, wait.extended].filter(Boolean).join(' / ') : item.wait?.waiting_on;
  if (waitText) rows.push({ labelKey: 'opscenter.cell.task_manager_mk2.tab.waiting_on', value: waitText });
  if (review?.where) rows.push({ labelKey: 'opscenter.cell.task_manager_mk2.tab.where', value: review.where });
  if (review?.link && review.link !== item.github_issue) rows.push({ labelKey: 'opscenter.cell.task_manager_mk2.tab.link', value: review.link });
  if (item.start_trigger) {
    rows.push({ labelKey: 'opscenter.cell.task_manager_mk2.tab.scheduled', value: new Date(item.start_trigger.fire_at * 1000).toLocaleString() });
  }
  const status = statusOf(item);
  return { statusKey: REAL_STATUS.has(status) ? statusKey(status) : null, rows };
}
