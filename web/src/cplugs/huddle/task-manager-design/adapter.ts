import { NUDGE_CATEGORY, STATUS_CATEGORY, messageTime, type HuddleItem, type TaskManagerMessage } from '../huddle-model';
import { latestMessage } from '../huddle-density';
import { reviewOf } from '../huddle-review';
import { statusOf } from '../huddle-status';
import { openQuestions } from '../task-manager-posts';
import { draftOf, toLocalInput } from '../task-manager-schedule';
import type { StepsEntry } from '../task-manager-steps';
import { t } from '../../sdk';
import type { Closure } from './closed-api';
import type { Message, Resource, Review, ReviewCheck, Schedule, Task, TaskState } from './model';
import { statusLineText } from './status-line';
import { newMessageIds, sharedOf, titleOf, type Entry, type Shared } from './task-view';
import { ageWords, closedWords, closerText, messageClock, runWords, type TaskClock } from './when';

const STATE_OF: Readonly<Record<string, TaskState>> = Object.freeze({
  question: 'question', review: 'review', working: 'working', waiting: 'waiting', scheduled: 'open', open: 'open', todo: 'later', done: 'closed',
});

const ISSUE = /^https:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/issues\/(\d+)$/;

const DEFAULT_AGENT = 'claude';

const RUNNING = 'inProgress';

export function stateOfItem(item: HuddleItem): TaskState {
  return STATE_OF[statusOf(item)] ?? 'open';
}

function resourceType(shared: Shared): string {
  if (shared.kind === 'round') return 'board';
  if (shared.kind === 'link') return 'link';
  if (shared.kind === 'file') return shared.file?.image ? 'image' : 'file';
  return 'page';
}

function isComment(message: TaskManagerMessage): boolean {
  return (message.kind as string) === 'comment' || message.quiet === true;
}

function timeOf(at: number | null | undefined, clock: TaskClock | null): string {
  if (!at) return '';
  return clock ? messageClock(at, clock.nowSec, clock.zone) : messageTime(at);
}

function scheduleOf(item: HuddleItem): Schedule | undefined {
  const trigger = item.start_trigger;
  if (!trigger) return undefined;
  const plan = draftOf(trigger.repeat);
  const kind = plan.kind === 'none' ? 'once' : (plan.kind as Schedule['kind']);
  return { kind, when: toLocalInput(trigger.fire_at), paused: trigger.paused === true, days: plan.days, hours: plan.hours, monthday: plan.monthday };
}

const UNDER_REVIEW: ReadonlySet<string> = new Set(['board', 'page']);

function roundOf(messages: readonly Message[], resources: readonly Resource[]): Resource[] {
  const last = messages.reduce((at, m, i) => (m.by === 'you' && !m.event && !m.comment ? i : at), -1);
  const fresh = new Set(messages.slice(last + 1).flatMap((m) => m.sharedIds ?? []));
  const round = resources.filter((r) => fresh.has(r.id));
  const subject = round.filter((r) => UNDER_REVIEW.has(r.type ?? ''));
  return subject.length ? subject : round.length ? round : [...resources];
}

export function checksOf(item: HuddleItem): ReviewCheck[] {
  return (item.review_checks ?? []).map((c) => ({ id: c.id, label: c.label, checked: !!c.checked, version: 1 }));
}

function reviewOfTask(item: HuddleItem, messages: readonly Message[], resources: readonly Resource[], clock: TaskClock | null): Review | undefined {
  const block = reviewOf(item);
  if (!block) return undefined;
  const trigger = item.start_trigger;
  const at = trigger?.repeat ? (trigger.last_fired_at ?? trigger.fire_at) : null;
  const run = at ? (clock ? runWords(at, clock.nowSec, clock.zone) : messageTime(at)) : undefined;
  return { version: 1, ...(run ? { run } : {}), resources: roundOf(messages, resources), checks: checksOf(item), history: [], where: block.where, link: block.link };
}

function waitSource(messages: readonly Message[]): number {
  return messages.map((m) => m.kind).lastIndexOf('waiting');
}

export function taskOf(entry: Entry, extra: { closure?: Closure | null; steps?: StepsEntry | null; clock?: TaskClock | null } = {}): Task {
  const { item } = entry;
  const clock = extra.clock ?? null;
  const fresh = new Set(newMessageIds(item));
  const shared = sharedOf(item);
  const thread = item.thread.filter((m) => m.category !== NUDGE_CATEGORY);
  const index = new Map(thread.map((m, at) => [m.id, at] as const));
  const resources: Resource[] = shared.map((s) => ({
    id: s.key, type: resourceType(s), name: s.name, rev: s.round?.revision, source: index.get(s.messageId), href: s.href, shared: s,
  }));
  const messages: Message[] = thread.map((m) => ({
    id: String(m.id), by: m.author === 'joe' ? 'you' : 'agent', time: timeOf(m.created_at, clock),
    text: m.category === STATUS_CATEGORY ? statusLineText(m.text) : m.text, read: m.category === STATUS_CATEGORY || !fresh.has(m.id), system: m.category === STATUS_CATEGORY,
    kind: m.kind, quote: m.quote?.text, event: m.kind === 'correction', comment: isComment(m), answered: m.answered,
    sharedIds: shared.filter((s) => s.messageId === m.id).map((s) => s.key),
  }));
  const closure = extra.closure ?? null;
  const state = closure ? 'closed' : stateOfItem(item);
  const review = state === 'review' ? reviewOfTask(item, messages, resources, clock) : undefined;
  const wait = item.wait ?? null;
  const issue = item.github_issue ? ISSUE.exec(item.github_issue) : null;
  const steps = extra.steps ?? null;
  const last = latestMessage(item);
  const closedAt = closure?.closed_at ?? null;
  return {
    id: item.id, title: titleOf(item), project: entry.project, state, agent: item.tagged_by || DEFAULT_AGENT,
    text: review ? (reviewOf(item)?.description || item.text) : item.text, original: item.text,
    age: last ? (clock ? ageWords(last.created_at, clock.nowSec, clock.zone) : messageTime(last.created_at)) : '',
    unread: item.unread === true, scheduled: item.status === 'scheduled' || undefined, messages, shared: resources, review, schedule: scheduleOf(item), note: item.note, parent: item.forked_from ?? undefined,
    blocker: state === 'waiting' && wait ? {
      summary: wait.waiting_on, reason: wait.waiting_on || t('cplug.huddle.tm.not_recorded'), owner: wait.kind || t('cplug.huddle.tm.not_recorded'),
      condition: wait.check_kind ? t(`cplug.huddle.wait.check_kind.${wait.check_kind}`) : t('cplug.huddle.tm.not_recorded'), source: waitSource(messages),
    } : undefined,
    workPlan: steps && steps.tasks.length ? {
      phase: steps.tasks.find((s) => s.status === 'in_progress')?.active_form ?? '', source: item.tagged_by || DEFAULT_AGENT, updated: '',
      steps: steps.tasks.map((s) => ({ text: s.subject, status: s.status === 'in_progress' ? RUNNING : s.status })),
    } : undefined,
    githubIssue: issue ? { url: item.github_issue!, repo: issue[1]!, number: Number(issue[2]), title: '' } : undefined,
    outcome: closure?.outcome, closedAt: closedAt ?? undefined,
    closedLabel: closure ? (closedAt ? (clock ? closedWords(closedAt, clock.nowSec, clock.zone) : messageTime(closedAt)) : t('cplug.huddle.tm.closure_time_unknown')) : undefined,
    closedBy: closure ? closerText({ closedBy: closure.closed_by ?? undefined }) : undefined,
    list: entry.list, asks: state === 'question' ? openQuestions(item) : [], item, canUndo: closure?.can_undo, closure: closure ?? undefined,
  };
}
