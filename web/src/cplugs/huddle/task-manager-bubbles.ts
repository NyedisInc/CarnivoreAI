/* the markdown body */
import type { TaskManagerMessage } from './huddle-model';
import { KIND_COLORS } from './task-manager-posts';
import { STATUS_ICON } from './huddle-status';

export type BubbleKind = 'info' | 'look' | 'question' | 'answer' | 'claude' | 'owner' | 'review' | 'form_answer';

export type BubbleSlot = 'quote' | 'form' | 'fold' | 'files' | 'actions' | 'outcome' | 'where' | 'link';

export interface BubbleVariant {
  labelKey: string | null;
  titleKey: string | null;
  tone: { color: string; colorBright: string };
  icon: string;
  slots: readonly BubbleSlot[];
}

const FORM_ANSWER_TONE = Object.freeze({ color: 'var(--oc-text-muted)', colorBright: 'var(--oc-text-secondary)' });
const OWNER_TONE = Object.freeze({ color: 'var(--oc-text-secondary)', colorBright: 'var(--oc-text-primary)' });
const WAITING_TONE = Object.freeze({ color: 'var(--oc-yellow)', colorBright: 'var(--oc-yellow-bright)' });

export const BUBBLES: Readonly<Record<BubbleKind, BubbleVariant>> = Object.freeze({
  info: { labelKey: 'cplug.huddle.thread.info', titleKey: 'cplug.huddle.thread.info_title', tone: KIND_COLORS.info, icon: 'status-info', slots: ['fold', 'files'] },
  look: { labelKey: 'cplug.huddle.thread.attention', titleKey: 'cplug.huddle.thread.attention_title', tone: KIND_COLORS.look, icon: 'status-look', slots: ['fold', 'files'] },
  question: { labelKey: 'cplug.huddle.thread.question', titleKey: null, tone: KIND_COLORS.question, icon: 'status-question', slots: ['form', 'fold', 'files'] },
  answer: { labelKey: 'cplug.huddle.thread.answer', titleKey: 'cplug.huddle.thread.answer_title', tone: KIND_COLORS.answer, icon: 'chat', slots: ['quote', 'fold', 'files'] },
  claude: { labelKey: null, titleKey: null, tone: KIND_COLORS.answer, icon: 'chat', slots: ['files'] },
  owner: { labelKey: null, titleKey: null, tone: OWNER_TONE, icon: 'person-bust', slots: ['files'] },
  form_answer: { labelKey: 'cplug.huddle.thread.form_answer', titleKey: 'cplug.huddle.thread.form_answer_title', tone: FORM_ANSWER_TONE, icon: 'list', slots: [] },
  review: { labelKey: 'cplug.huddle.review.label', titleKey: null, tone: KIND_COLORS.review, icon: STATUS_ICON.review, slots: ['link', 'where'] },
});

export const BUBBLE_KINDS: readonly BubbleKind[] = Object.freeze(Object.keys(BUBBLES) as BubbleKind[]);

export function isFormAnswer(message: Pick<TaskManagerMessage, 'answers' | 'answers_to'>): boolean {
  return message.answers_to != null && message.answers != null;
}

export function bubbleKindOf(message: Pick<TaskManagerMessage, 'author' | 'kind' | 'answers' | 'answers_to'>): BubbleKind {
  if (isFormAnswer(message)) return 'form_answer';
  if (message.author !== 'claude') return 'owner';
  if (message.kind === 'attention') return 'look';
  if (message.kind === 'question' || message.kind === 'answer' || message.kind === 'info') return message.kind;
  return 'claude';
}

export function threadTone(message: Pick<TaskManagerMessage, 'author' | 'kind' | 'answers' | 'answers_to'>): string {
  return BUBBLES[bubbleKindOf(message)].tone.color;
}
