/* the review card */
import { isSystemLine, type HuddleItem, type TaskManagerMessage } from './huddle-model';
import { openQuestions, unreadPosts } from './task-manager-posts';
import { statusOf } from './huddle-status';
import type { TaskState } from '../sdk/ui';

export const DENSITIES = ['compact', 'normal', 'full'] as const;
export type HuddleDensity = (typeof DENSITIES)[number];
export const DEFAULT_DENSITY: HuddleDensity = 'normal';
export const MAX_TITLE = 120;

export interface RowParts {
  extras: boolean;
  description: boolean;
  latest: boolean;
  questions: boolean;
  reply: boolean;
  review: boolean;
  posts: 'block' | 'count' | null;
}

export function densityFrom(settings: Record<string, unknown> | undefined): HuddleDensity {
  const value = settings?.density;
  return (DENSITIES as readonly unknown[]).includes(value) ? (value as HuddleDensity) : DEFAULT_DENSITY;
}

export function rowParts(density: HuddleDensity, item: HuddleItem): RowParts {
  const hasPosts = unreadPosts(item).length > 0;
  if (density === 'compact') {
    return { extras: false, description: false, latest: statusOf(item) === 'question', questions: false, reply: false, review: false, posts: hasPosts ? 'count' : null };
  }
  const questions = openQuestions(item).length > 0;
  return {
    extras: true,
    description: density === 'full' && rowTitle(item) !== item.text,
    latest: false,
    questions,
    reply: replyBoxShows(item),
    review: true,
    posts: hasPosts ? 'block' : null,
  };
}

export function wrapperParts(state: TaskState, item: HuddleItem): RowParts {
  if (state === 'compact') return { ...rowParts('compact', item), extras: true, latest: false };
  return { ...rowParts('normal', item), description: false, latest: false, questions: false, reply: false, review: false };
}

export function rowTitle(item: Pick<HuddleItem, 'title' | 'text'>): string {
  const title = item.title?.trim();
  return title ? title : item.text;
}

export function latestMessage(item: Pick<HuddleItem, 'thread'>): TaskManagerMessage | null {
  return openQuestions(item).at(-1) ?? item.thread.filter((m) => !isSystemLine(m)).at(-1) ?? null;
}

export function replyBoxShows(item: HuddleItem): boolean {
  const status = statusOf(item);
  return status === 'question' || status === 'review';
}

export function focusOpens(density: HuddleDensity): boolean {
  return density === 'compact';
}
