import { ownQuestion, type HuddleItem, type TaskManagerMessage } from './huddle-model';
import { statusIconColor } from './huddle-status';
import { mdPlain } from './task-manager-markdown';

export type TaskManagerPostKind = 'info' | 'attention';

export function postKindOf(message: Pick<TaskManagerMessage, 'author' | 'kind'>): TaskManagerPostKind | null {
  if (message.author !== 'claude') return null;
  if (message.kind === 'info' || message.kind === 'answer') return 'info';
  return message.kind === 'attention' ? 'attention' : null;
}

export interface PostKindMeta {
  icon: string;
  color: string;
  colorBright: string;
  tint: string;
  countField: 'info_unread' | 'attention_unread';
  flagField: 'info_unseen' | 'attention_unseen';
  readKey: string;
  countKey: string;
}

export const KIND_COLORS = Object.freeze({
  question: { color: statusIconColor('question'), colorBright: statusIconColor('question') },
  info: { color: 'var(--oc-violet)', colorBright: 'var(--oc-violet)' },
  look: { color: 'var(--oc-cyan)', colorBright: 'var(--oc-cyan)' },
  answer: { color: 'var(--oc-orange)', colorBright: 'var(--oc-orange)' },
  review: { color: 'var(--oc-green-bright)', colorBright: 'var(--oc-green-bright)' },
});

export function postTone(message: Pick<TaskManagerMessage, 'author' | 'kind'>): { color: string; colorBright: string } {
  if (message.author === 'claude' && message.kind === 'answer') return KIND_COLORS.answer;
  return POST_KINDS[postKindOf(message) ?? 'info'];
}

export const QUESTION_BLOCK = Object.freeze({ icon: 'status-question', ...KIND_COLORS.question, labelKey: 'cplug.huddle.question.block' });

export const POST_KINDS: Readonly<Record<TaskManagerPostKind, PostKindMeta>> = Object.freeze({
  info: {
    icon: 'status-info', ...KIND_COLORS.info, tint: KIND_COLORS.info.color,
    countField: 'info_unread', flagField: 'info_unseen', readKey: 'cplug.huddle.info.read', countKey: 'cplug.huddle.info.count',
  },
  attention: {
    icon: 'status-look', ...KIND_COLORS.look, tint: KIND_COLORS.look.color,
    countField: 'attention_unread', flagField: 'attention_unseen', readKey: 'cplug.huddle.look.read', countKey: 'cplug.huddle.look.count',
  },
});

export const POST_KIND_LIST: readonly TaskManagerPostKind[] = ['info', 'attention'];

export function unreadPosts(item: Pick<HuddleItem, 'thread'>): TaskManagerMessage[] {
  return item.thread.filter((m) => postKindOf(m) !== null && m.unread === true);
}

export function unreadCount(item: Pick<HuddleItem, 'thread' | 'info_unread' | 'attention_unread'>, kind: TaskManagerPostKind): number {
  return item[POST_KINDS[kind].countField] ?? unreadPosts(item).filter((m) => postKindOf(m) === kind).length;
}

export function openQuestions(item: Pick<HuddleItem, 'id' | 'kind' | 'created_by' | 'status' | 'text' | 'thread' | 'created_seq'>): TaskManagerMessage[] {
  const own = ownQuestion(item);
  return [...(own ? [own] : []), ...item.thread.filter((m) => m.kind === 'question' && !m.answered)];
}

export function rowQuestionPick(feed: readonly Pick<TaskManagerMessage, 'id' | 'kind'>[]): { shown: number | null; hidden: number } {
  const ids = feed.filter((m) => m.kind === 'question').map((m) => m.id);
  return { shown: ids.at(-1) ?? null, hidden: Math.max(0, ids.length - 1) };
}

export function rowFeed(item: Pick<HuddleItem, 'id' | 'kind' | 'created_by' | 'status' | 'text' | 'thread' | 'created_seq'>): TaskManagerMessage[] {
  const cutoff = lastOwnReplyId(item);
  const claude = [...unreadPosts(item), ...openQuestions(item)].filter((m) => cutoff === 0 || m.id > cutoff || isFormAsk(m));
  return claude.sort((a, b) => a.created_at - b.created_at || a.id - b.id);
}

export function lastOwnReplyId(item: Pick<HuddleItem, 'thread'>): number {
  return item.thread.reduce((top, m) => (isOwnReply(m) && m.id > top ? m.id : top), 0);
}

export function isOwnReply(message: Pick<TaskManagerMessage, 'author' | 'kind'>): boolean {
  return message.author === 'joe' && message.kind === 'reply';
}

export function postBody(text: string): string {
  return text;
}

export function isShiftDismiss(event: Pick<MouseEvent, 'shiftKey' | 'target'>): boolean {
  return event.shiftKey && isDismissTarget(event.target as Element | null);
}

export function isDismissTarget(target: Element | null): boolean {
  return !(target && typeof target.closest === 'function' && target.closest('a, button, input, textarea, select, summary'));
}

export function isFoldToggle(event: Pick<MouseEvent, 'shiftKey' | 'target'>, selected: string): boolean {
  return !event.shiftKey && selected === '' && isDismissTarget(event.target as Element | null);
}

export const FOLD_CHARS = 240;
export const FOLD_LINES = 3;
export const LEAD_CHARS = 100;

export interface PostFold {
  full: string;
  folded: string;
  foldable: boolean;
  lead: boolean;
  limit: number;
  more: boolean;
}

export const ONE_LINE_CHARS = 80;

export function oneLineFold(text: string): PostFold {
  const lines = text.split('\n');
  const first = (lines[0] ?? '').trim();
  const foldable = lines.length > 1 || first.length > ONE_LINE_CHARS;
  if (!foldable) return { full: text, folded: text, foldable: false, lead: false, limit: 0, more: false };
  return { full: text, folded: first, foldable, lead: false, limit: ONE_LINE_CHARS, more: true };
}

export function postFold(text: string, oneLine = false): PostFold {
  if (oneLine) return oneLineFold(text);
  const lines = text.split('\n');
  const foldable = text.length > FOLD_CHARS || lines.length > FOLD_LINES;
  if (!foldable) return { full: text, folded: text, foldable: false, lead: false, limit: 0, more: false };
  const first = (lines[0] ?? '').trim();
  if (lines.length > 1 && first.length > 0 && first.length <= LEAD_CHARS && !/\*\*/.test(mdPlain(first))) return { full: text, folded: first, foldable, lead: true, limit: 0, more: false };
  return { full: text, folded: lines.slice(0, FOLD_LINES).join('\n'), foldable, lead: false, limit: FOLD_CHARS, more: true };
}

export function askFold(message: Pick<TaskManagerMessage, 'text' | 'context' | 'questions' | 'form'>, oneLine = false): AskFold {
  const parts = askParts(message);
  if (!parts) {
    const fold = postFold(message.text, oneLine);
    return { foldable: fold.foldable, text: fold.folded, context: '', shown: 0, limit: fold.limit, more: fold.more };
  }
  if (isFormAsk(message) && oneLine && askLead(message) !== '') return { foldable: true, text: '', context: askLead(message), shown: 0, limit: ONE_LINE_CHARS, more: true };
  if (isFormAsk(message)) return { foldable: false, text: '', context: '', shown: 0, limit: 0, more: false };
  const whole = [parts.context, ...parts.questions].filter(Boolean).join('\n');
  if (oneLine) {
    const lead = oneLineFold(parts.context || parts.questions[0] || '');
    return { foldable: whole.includes('\n') || lead.foldable, text: '', context: lead.folded, shown: 0, limit: ONE_LINE_CHARS, more: true };
  }
  const foldable = whole.length > FOLD_CHARS || whole.split('\n').length > FOLD_LINES;
  if (!foldable) return { foldable, text: '', context: parts.context, shown: parts.questions.length, limit: 0, more: false };
  const context = postFold(parts.context);
  return { foldable, text: '', context: context.folded, shown: 1, limit: context.limit, more: context.more };
}

export interface AskFold {
  foldable: boolean;
  text: string;
  context: string;
  shown: number;
  limit: number;
  more: boolean;
}

export function askParts(message: Pick<TaskManagerMessage, 'context' | 'questions'>): { context: string; questions: string[] } | null {
  const questions = message.questions ?? [];
  return questions.length ? { context: message.context ?? '', questions } : null;
}

export function askLead(message: Pick<TaskManagerMessage, 'context'>): string {
  return (message.context ?? '').split('\n').map((line) => line.trim()).find((line) => line.length > 0) ?? '';
}

export function isFormAsk(message: Pick<TaskManagerMessage, 'form'>): boolean {
  return (message.form?.length ?? 0) > 0;
}

export function hasNumberedAsk(item: Pick<HuddleItem, 'id' | 'kind' | 'created_by' | 'status' | 'text' | 'thread' | 'created_seq'>): boolean {
  return openQuestions(item).some((m) => askParts(m) !== null && !isFormAsk(m));
}

export function hasFormAsk(item: Pick<HuddleItem, 'id' | 'kind' | 'created_by' | 'status' | 'text' | 'thread' | 'created_seq'>): boolean {
  return openQuestions(item).some(isFormAsk);
}
