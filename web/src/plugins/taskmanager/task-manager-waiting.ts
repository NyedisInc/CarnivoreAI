import type { HuddleItem } from './huddle-model';
import { KIND_COLORS, POST_KINDS, unreadCount } from './task-manager-posts';
import { SECTION_ICON, sectionOf } from './task-manager-status-sections';

export type WaitingKind = 'question' | 'info';

export interface WaitingMark {
  kind: WaitingKind;
  count: number;
  icon: string;
  color: string;
  titleKey: string;
}

const LOOK: Readonly<Record<WaitingKind, Pick<WaitingMark, 'icon' | 'color' | 'titleKey'>>> = Object.freeze({
  question: { icon: SECTION_ICON.question, color: KIND_COLORS.question.color, titleKey: 'cplug.huddle.waiting.question' },
  info: { icon: POST_KINDS.info.icon, color: POST_KINDS.info.color, titleKey: POST_KINDS.info.countKey },
});

export function waitingMarks(items: readonly HuddleItem[], skip: readonly WaitingKind[] = []): WaitingMark[] {
  const counts: Record<WaitingKind, number> = { question: 0, info: 0 };
  for (const item of items) {
    if (sectionOf(item) === 'question') counts.question += 1;
    counts.info += unreadCount(item, 'info');
  }
  return (['question', 'info'] as const)
    .filter((kind) => counts[kind] > 0 && !skip.includes(kind))
    .map((kind) => ({ kind, count: counts[kind], ...LOOK[kind] }));
}
