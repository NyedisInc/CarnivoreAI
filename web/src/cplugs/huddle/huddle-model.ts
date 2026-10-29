
import type { AskAnswer, AskQuestion } from './ask/ask-model';

export type TaskManagerActor = 'joe' | 'claude';

export const STORED_STATES = ['open', 'todo', 'waiting', 'review', 'done'] as const;

export type TaskManagerState = (typeof STORED_STATES)[number];

export type TaskManagerKind = '' | 'question' | 'done' | 'waiting' | 'info';

export function isInfo(item: Pick<HuddleItem, 'kind'>): boolean {
  return item.kind === 'info';
}

export type TaskManagerMessageKind = 'question' | 'reply' | 'info' | 'attention' | 'answer' | 'correction';

export interface TaskManagerQuote {
  id: number | null;
  text: string;
}

export interface TaskManagerFile {
  id: string;
  name: string;
  mime: string;
  size: number;
  image: boolean;
}

export interface TaskManagerArtifact {
  id: string;
  title: string;
  description: string;
  size: number;
}

export const NUDGE_CATEGORY = 'nudge';
export const STATUS_CATEGORY = 'status';

export const isSystemLine = (message: { category?: string }): boolean => message.category === NUDGE_CATEGORY || message.category === STATUS_CATEGORY;

export interface TaskManagerMessage {
  id: number;
  item_id: number;
  author: TaskManagerActor;
  kind: TaskManagerMessageKind;
  text: string;
  answered: boolean;
  created_at: number;
  seq: number;
  unread?: boolean;
  context?: string;
  questions?: string[];
  form?: AskQuestion[];
  answers_to?: number;
  freeform?: boolean;
  answers?: Record<string, AskAnswer>;
  files?: TaskManagerFile[];
  artifact?: TaskManagerArtifact;
  board_round?: TaskManagerBoardRound;
  board?: TaskManagerBoardCard;
  quote?: TaskManagerQuote;
  schedule?: TaskManagerScheduleOffer;
  retracts?: { outcome: 'completed' | 'cancelled'; closure_id: number; closed_at: number | null; closed_by: string | null; restored_state: string };
  quiet?: boolean;
  category?: string;
}

export interface TaskManagerScheduleOffer { when: string; title: string; state: 'offered' | 'accepted'; accepted_at?: string }

export interface TaskManagerBoardRound { slug: string; round: string; revision: string }

export interface TaskManagerBoardCard { slug: string; revision: string; title: string; summary: string }

export interface ReviewCheckRow {
  id: string;
  label: string;
  checked: boolean;
  checked_at: number | null;
  checked_by: string | null;
}

export interface HuddleItem {
  id: number;
  list: string;
  lane?: 'task_manager' | 'swarm';
  text: string;
  note: string;
  position: number;
  created_by: TaskManagerActor;
  state: TaskManagerState;
  kind: TaskManagerKind;
  number?: number | null;
  placeholder?: true;
  revision: number;
  created_seq: number;
  seq: number;
  deleted: boolean;
  unread?: boolean;
  info_unseen?: boolean;
  info_unread?: number;
  attention_unseen?: boolean;
  attention_unread?: number;
  status?: string;
  section?: string;
  needs_you?: boolean;
  needs_action?: string | null;
  group?: number | null;
  review_description?: string | null;
  review_summary?: string | null;
  review_link?: string | null;
  review_where?: string | null;
  review_action?: string | null;
  review_checks?: ReviewCheckRow[];
  title?: string | null;
  marker?: string | null;
  forked_from?: number | null;
  forked_from_title?: string | null;
  from_project?: { id: string; name: string } | null;
  tagged_session_key?: string;
  tagged_by?: string | null;
  wait?: {
    waiting_on: string; kind: string; set_at: number; expect_by: number; deadline: number; extended: number; extend_reason: string;
    check_kind: string; check_result: string; status: 'active' | 'escalated';
  };
  blockers?: Array<{ id: number; kind: string; text: string; created_by: string; created_at: number; holding?: number | null }>;
  github_issue?: string | null;
  from_inbox?: { id: number; text: string; direct?: boolean };
  start_trigger?: TaskManagerTrigger | null;
  nudge?: { count: number; last_at: number | null; stalled: boolean };
  thread: TaskManagerMessage[];
  thread_count?: number;
  thread_slim?: boolean;
}

export interface TaskManagerTrigger {
  kind: string;
  fire_at: number;
  fire_at_iso?: string | null;
  fired_at: number | null;
  last_error: string | null;
  repeat?: TaskManagerRepeat | null;
  paused?: boolean;
  last_fired_at?: number | null;
}

export interface TaskManagerRepeat {
  freq: 'daily' | 'weekly' | 'hourly' | 'monthly';
  time?: string;
  byweekday?: number[];
  monthday?: number;
  interval?: number;
}

export interface TaskManagerItemGroup {
  id: number;
  list: string;
  name: string;
  position: number;
  folded: boolean;
}

export interface TaskManagerListBody {
  list: string;
  revision: number;
  cursor: number;
  inbox?: TaskManagerInboxEntry[];
  groups?: TaskManagerItemGroup[];
  done_count?: number;
  items: HuddleItem[];
  delta_seq?: number;
  delta_epoch?: string;
}

export interface TaskManagerInboxEntry {
  id: number;
  text: string;
  status: 'queued' | 'filing' | 'stuck';
  created_at: number;
}

export type TaskManagerAddOutcome = 'queued' | 'added' | 'failed' | 'kept';

export interface TaskManagerListRow {
  key: string;
  name: string | null;
  project_id: number | null;
  items: number;
  open: number;
  review: number;
  questions: number;
  claude_seq: number;
  unread?: number;
  untold?: boolean;
  waiting_to_send?: number;
  incomplete?: number;
  needs_you?: number;
  attention?: number;
  status_counts?: Record<string, number>;
  nudge?: boolean;
  inbox_via_session?: boolean;
}

export interface TaskManagerSession {
  id: string;
  label: string;
  tmux_session: string | null;
  project: string | null;
  activity_status: string | null;
  elsewhere?: boolean;
}

export type SendReason = 'last_task_manager_caller' | 'only_session' | 'pick' | 'picked' | 'lead';

export interface SendChoice {
  sessions: TaskManagerSession[];
  default: string | null;
  reason: SendReason;
}

export const TASK_MANAGER_FAMILY = 'cplug.huddle.list';

export const ALL_LIST = 'all';

export const AGGREGATE = 'aggregate';

export interface TaskManagerGroup {
  list: string;
  name: string | null;
  project_id: number | null;
  revision: number;
  groups?: TaskManagerItemGroup[];
  inbox?: TaskManagerInboxEntry[];
  done_count?: number;
  items: HuddleItem[];
}

export interface TaskManagerAggregateBody {
  cursor: number;
  groups: TaskManagerGroup[];
  delta_seq?: number;
  delta_epoch?: string;
}

export const LIST_PARAM = 'list';

export function listFromSearch(search: string): string | null {
  const value = new URLSearchParams(search).get(LIST_PARAM);
  return value !== null && /^(aggregate|all|agent:[1-9][0-9]{0,9}|[1-9][0-9]{0,9})$/.test(value) ? value : null;
}

export function isAgentList(key: string): boolean {
  return /^agent:[1-9][0-9]{0,9}$/.test(key);
}

export function listFallback(key: string): { key: string; id: string } {
  if (key === ALL_LIST) return { key: 'cplug.huddle.list.shared', id: key };
  if (isAgentList(key)) return { key: 'cplug.huddle.list.agent', id: key.slice('agent:'.length) };
  return { key: 'cplug.huddle.list.project', id: key };
}

export function listProjectId(list: string): number | null {
  return /^[1-9][0-9]{0,9}$/.test(list) ? Number(list) : null;
}

export function serverKey(selected: string): string {
  return selected === AGGREGATE ? ALL_LIST : selected;
}

export function isApproved(state: TaskManagerState): boolean {
  return state === 'done';
}

export function stateKey(state: TaskManagerState): string {
  return `cplug.huddle.state.${state}`;
}

export function visibleItems(items: readonly HuddleItem[], hideCompleted: boolean): HuddleItem[] {
  return items.filter((i) => !i.placeholder && !(hideCompleted && isApproved(i.state)));
}

/*  hidden  */
export function fullMove(all: readonly number[], visible: readonly number[], from: number, to: number): [number, number] {
  const moved = visible[from];
  if (moved === undefined) return [from, from];
  const order = moveId(visible, from, to);
  const at = order.indexOf(moved);
  const rest = all.filter((id) => id !== moved);
  const next = order[at + 1];
  const prev = order[at - 1];
  const target = next !== undefined ? rest.indexOf(next) : prev !== undefined ? rest.indexOf(prev) + 1 : 0;
  return [all.indexOf(moved), target];
}

export function completedCount(items: readonly HuddleItem[]): number {
  return items.reduce((n, i) => n + (isApproved(i.state) ? 1 : 0), 0);
}

export function wholeEntry(text: string): string {
  return text.replace(/\r\n?/g, '\n').trim();
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

export function messageTime(at: number, now: number = Date.now() / 1000): string {
  const when = new Date(at * 1000);
  const today = new Date(now * 1000);
  const clock = `${pad2(when.getHours())}:${pad2(when.getMinutes())}`;
  const sameDay = when.getFullYear() === today.getFullYear() && when.getMonth() === today.getMonth() && when.getDate() === today.getDate();
  return sameDay ? clock : `${pad2(when.getMonth() + 1)}-${pad2(when.getDate())} ${clock}`;
}

export function ownQuestion(item: Pick<HuddleItem, 'id' | 'kind' | 'created_by' | 'status' | 'text' | 'thread' | 'created_seq'>): TaskManagerMessage | null {
  if (item.kind !== 'question' || item.created_by !== 'claude') return null;
  if (item.thread.some((m) => m.kind === 'question')) return null;
  const pending = item.status ? item.status === 'question' : !item.thread.some((m) => m.author === 'joe');
  if (!pending) return null;
  return { id: -item.id, item_id: item.id, author: 'claude', kind: 'question', text: item.text, answered: false, created_at: 0, seq: item.created_seq } as TaskManagerMessage;
}

export function hasOpenQuestion(item: HuddleItem): boolean {
  return item.thread.some((m) => m.kind === 'question' && !m.answered) || ownQuestion(item) !== null;
}

export function moveId(ids: readonly number[], from: number, to: number): number[] {
  const out = [...ids];
  if (from < 0 || from >= out.length) return out;
  const [moved] = out.splice(from, 1);
  out.splice(Math.max(0, Math.min(out.length, to)), 0, moved as number);
  return out;
}

export function surfaceFor(lists: readonly TaskManagerListRow[], seen: number): { surface: boolean; newest: number; list: string | null } {
  let newest = seen;
  let list: string | null = null;
  for (const row of lists) {
    if (row.claude_seq > newest) {
      newest = row.claude_seq;
      list = row.key;
    }
  }
  return { surface: list !== null, newest, list };
}

export function waitingQuestions(lists: readonly TaskManagerListRow[]): number | null {
  const n = lists.reduce((sum, row) => sum + (row.questions || 0), 0);
  return n > 0 ? n : null;
}

export function needsYouTotal(lists: readonly Pick<TaskManagerListRow, 'key' | 'needs_you' | 'attention' | 'status_counts'>[], selected: string, statuses?: readonly string[]): number | null {
  const own = (row: Pick<TaskManagerListRow, 'needs_you' | 'attention' | 'status_counts'>): number =>
    statuses && row.status_counts ? statuses.reduce((sum, status) => sum + (row.status_counts?.[status] ?? 0), 0) : (row.attention ?? row.needs_you ?? 0);
  const n = lists.filter((row) => selected === AGGREGATE || row.key === selected).reduce((sum, row) => sum + own(row), 0);
  return n > 0 ? n : null;
}

export function unreadTotal(lists: readonly Pick<TaskManagerListRow, 'unread'>[]): number | null {
  const n = lists.reduce((sum, row) => sum + (row.unread || 0), 0);
  return n > 0 ? n : null;
}

export function moveTargets<T extends Pick<TaskManagerListRow, 'key'>>(lists: readonly T[], from: string): T[] {
  return lists.filter((row) => row.key !== AGGREGATE && row.key !== from);
}

export function refusalCode(payload: unknown): string | null {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  const code = (detail as { code?: unknown } | null)?.code;
  return typeof code === 'string' ? code : null;
}

export function dropIndex(middles: readonly number[], y: number, from: number): number {
  let index = 0;
  for (let i = 0; i < middles.length; i += 1) {
    if (i === from) continue;
    if (y > (middles[i] as number)) index += 1;
  }
  return index;
}

export interface TaskManagerSection {
  group: TaskManagerItemGroup | null;
  items: HuddleItem[];
}

export function sectionsOf(items: readonly HuddleItem[], groups: readonly TaskManagerItemGroup[] = []): TaskManagerSection[] {
  const ordered = [...groups].sort((x, y) => x.position - y.position || x.id - y.id);
  const known = new Set(ordered.map((g) => g.id));
  const out: TaskManagerSection[] = [{ group: null, items: [] }, ...ordered.map((group) => ({ group, items: [] as HuddleItem[] }))];
  for (const item of items) {
    const at = item.group != null && known.has(item.group) ? ordered.findIndex((g) => g.id === item.group) + 1 : 0;
    (out[at] as TaskManagerSection).items.push(item);
  }
  return out;
}

export function regroup(items: readonly HuddleItem[], groups: readonly TaskManagerItemGroup[], id: number,
  group: number | null, index: number | null): HuddleItem[] {
  const moved = items.find((i) => i.id === id);
  if (!moved) return [...items];
  const sections = sectionsOf(items.filter((i) => i.id !== id), groups);
  const target = sections.find((s) => (s.group?.id ?? null) === group) ?? (sections[0] as TaskManagerSection);
  const at = index === null ? target.items.length : Math.max(0, Math.min(target.items.length, index));
  target.items.splice(at, 0, { ...moved, group });
  return sections.flatMap((s) => s.items).map((i, n) => (i.position === n ? i : { ...i, position: n }));
}

/*  hidden  */
export function sectionIndex(all: readonly number[], visible: readonly number[], at: number): number {
  const next = visible[at];
  if (next !== undefined) return all.indexOf(next);
  const last = visible[visible.length - 1];
  return last !== undefined ? all.indexOf(last) + 1 : all.length;
}

export interface SectionBox {
  key: number | null;
  top: number;
  bottom: number;
  middles: number[];
}

export function dropTarget(boxes: readonly SectionBox[], y: number, from: { key: number | null; index: number }): { key: number | null; index: number } {
  if (!boxes.length) return { ...from };
  const box = boxes.find((b) => y < b.bottom) ?? (boxes[boxes.length - 1] as SectionBox);
  const skip = box.key === from.key ? from.index : -1;
  return { key: box.key, index: dropIndex(box.middles, y, skip) };
}
