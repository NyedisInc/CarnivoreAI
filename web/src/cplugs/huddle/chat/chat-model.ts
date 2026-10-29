import { hasOpenQuestion, type HuddleItem } from '../huddle-model';
import { statusOf } from '../huddle-status';
import type { AuthorCrumb, SwarmAgentState, SwarmEntry, SwarmQuestion } from './chat-api';

const TARGET = /^agent:([1-9][0-9]{0,9})$/;

export function agentIdOf(instance: string | undefined): number | null {
  const tail = instance?.slice(instance.indexOf(':') + 1);
  const match = tail ? TARGET.exec(tail) : null;
  return match ? Number(match[1]) : null;
}

export function chatSlotId(agentId: number): string {
  return `huddle.chat:agent:${agentId}`;
}

export function needsOwner(entry: SwarmEntry): boolean {
  if (entry.kind !== 'card') return false;
  if (decisionOf(entry.item)) return false;
  const status = statusOf(entry.item);
  return status === 'question' || status === 'review' || hasOpenQuestion(entry.item);
}

export function visibleEntries(entries: readonly SwarmEntry[], waitingOnly: boolean): SwarmEntry[] {
  const drawn = entries.filter(draws);
  return waitingOnly ? drawn.filter(needsOwner) : drawn;
}

export function waitingCount(entries: readonly SwarmEntry[]): number {
  return entries.filter(needsOwner).length;
}

export type CardVariant = 'ask' | 'withdrawn' | 'promotion' | 'closed' | null;

export function cardVariant(item: HuddleItem): CardVariant {
  const ref = (item as { swarm_ref?: string | null }).swarm_ref ?? '';
  if (ref.startsWith('question:')) return 'ask';
  if (ref.startsWith('closed:')) return 'closed';
  if (ref.startsWith('withdrawn:')) return 'withdrawn';
  if (ref.startsWith('promotion:')) return 'promotion';
  return null;
}

export interface DecisionKeys {
  yes: string | null;
  no: string;
  noText: string;
}

const GENERIC: DecisionKeys = { yes: 'cplug.huddle.chat.decide.approve', no: 'cplug.huddle.chat.decide.decline', noText: 'cplug.huddle.chat.decide.decline' };
const BY_PREFIX: Array<[string, DecisionKeys]> = [
  ['trust:', { yes: 'cplug.huddle.chat.decide.trust', no: 'cplug.huddle.chat.decide.not_now', noText: 'cplug.huddle.chat.decide.not_now' }],
  ['held:', { yes: 'cplug.huddle.chat.decide.deliver', no: 'cplug.huddle.chat.decide.deny', noText: 'cplug.huddle.chat.decide.deny' }],
  ['choice:', { yes: 'cplug.huddle.chat.decide.yes', no: 'cplug.huddle.chat.decide.no', noText: 'cplug.huddle.chat.decide.no' }],
  ['import:', { yes: 'cplug.huddle.chat.decide.allow', no: 'cplug.huddle.chat.decide.deny', noText: 'cplug.huddle.chat.decide.deny' }],
  ['promotion:', { yes: 'cplug.huddle.chat.promotion.keep', no: 'cplug.huddle.chat.promotion.flip_back', noText: 'cplug.huddle.chat.promotion.flip_text' }],
  ['visibility:', GENERIC],
  ['gitinit:', GENERIC],
  ['conflict:', GENERIC],
  ['suggest:', GENERIC],
];

export function decisionKeys(item: HuddleItem): DecisionKeys | null {
  const ref = (item as { swarm_ref?: string | null }).swarm_ref ?? '';
  const keys = BY_PREFIX.find(([prefix]) => ref.startsWith(prefix))?.[1] ?? null;
  return keys && ref.startsWith('choice:') && ref.endsWith(':no') ? { ...keys, yes: null } : keys;
}

export function messageEntryId(ref: string | null | undefined): string | null {
  return ref && /^huddle:msg:[1-9][0-9]*$/.test(ref) ? ref.slice('huddle:'.length) : null;
}

export function decisionOf(item: HuddleItem): 'done' | 'done_with_note' | null {
  for (const value of [statusOf(item), item.state]) {
    if (value === 'done') return item.note?.trim() ? 'done_with_note' : 'done';
  }
  return null;
}

export function canApprove(item: HuddleItem): boolean {
  return decisionOf(item) === null;
}

function textField(entry: unknown, key: string): string {
  const value = (entry as Record<string, unknown> | null)?.[key];
  return typeof value === 'string' ? value.trim() : '';
}

export function fallbackText(entry: unknown): string {
  return textField(entry, 'text');
}

/* anything at all */
export function draws(entry: SwarmEntry): boolean {
  switch (entry.kind) {
    case 'card':
    case 'traffic':
      return true;
    case 'event':
      return !!entry.receipt || !!textField(entry, 'text');
    default:
      return !!fallbackText(entry);
  }
}

export function menuActions(state: SwarmAgentState | null): Array<'sleep' | 'wake_fresh' | 'resume'> {
  if (state === 'awake' || state === 'waking') return ['sleep'];
  if (state === 'asleep') return ['wake_fresh', 'resume'];
  return [];
}

export function menuHasTurnOff(state: SwarmAgentState | null, rank: string | null): boolean {
  return state !== null && state !== 'torn_down' && rank !== null && rank !== 'alpha';
}

export function menuHasRewind(state: SwarmAgentState | null): boolean {
  return state !== null && state !== 'torn_down';
}

export function rewindBlock(state: SwarmAgentState | null): string | null {
  return state === 'asleep' ? null : 'cplug.huddle.chat.rewind.block_awake';
}

export function checkpointBlock(kind: string): string | null {
  return kind === 'flip_back' ? 'cplug.huddle.chat.rewind.block_flip_back' : null;
}

type Say = (key: string, params?: Record<string, string | number>) => string;

const TRAFFIC_STATUSES = ['queued', 'held', 'delivering', 'delivered', 'failed', 'expired'];
const EVENT_KINDS = ['spawned', 'reported', 'accepted', 'asked', 'answered', 'escalated', 'learned', 'promoted'];

function plain(name: string): string {
  return name.replace(/[_:.-]+/g, ' ').trim();
}

export function trafficStatusLabel(status: string, say: Say): string {
  return TRAFFIC_STATUSES.includes(status) ? say(`cplug.huddle.chat.traffic.status.${status}`) : plain(status);
}

export function eventLabel(event: string, say: Say): string {
  return EVENT_KINDS.includes(event) ? say(`cplug.huddle.chat.event.${event}`) : plain(event);
}

export interface EntryHead {
  path: AuthorCrumb[];
  at: number;
  more: number;
}

export function questionOf(entry: SwarmEntry): SwarmQuestion | null {
  return entry.kind === 'card' && entry.question ? entry.question : null;
}

export function headOf(entry: SwarmEntry): EntryHead | null {
  const question = questionOf(entry);
  const first = question?.askers?.[0];
  const path = first?.author_path?.length ? first.author_path : entry.author_path;
  if (!path?.length) return null;
  return { path, at: question?.asked_at ?? entry.at, more: Math.max(0, (question?.askers?.length ?? 0) - 1) };
}

export type Direction = 'to' | 'from' | null;

export interface BurstParty {
  key: string;
  dir: Direction;
  path: AuthorCrumb[];
  agentId: number | null;
  sessionUuid: string | null;
  owner: boolean;
}

export interface ChatSelf {
  id: number | null;
  name: string;
}

export interface PartyLookup {
  idOfName?: (name: string) => number | null;
  idOfUuid?: (uuid: string) => number | null;
}

export type ChatRow =
  | { kind: 'entry'; entry: SwarmEntry; party: BurstParty | null; first: boolean; at: number }
  | { kind: 'fold'; id: string; entries: SwarmEntry[] };

export function isQuiet(entry: SwarmEntry): boolean {
  return entry.kind === 'event' && !entry.receipt;
}

export function partyOf(entry: SwarmEntry, self: ChatSelf, look: PartyLookup = {}): BurstParty | null {
  if (entry.kind === 'traffic') {
    const uuid = entry.peer_session_uuid || null;
    const byUuid = uuid ? (look.idOfUuid?.(uuid) ?? null) : null;
    if (entry.direction === 'out') {
      const agentId = byUuid ?? (entry.peer ? (look.idOfName?.(entry.peer) ?? null) : null);
      const name = entry.peer || '';
      return { key: `to:${uuid ?? agentId ?? name}`, dir: 'to', path: [{ kind: 'agent', name, agent_id: agentId }], agentId, sessionUuid: uuid, owner: false };
    }
    const path = entry.author_path?.length ? entry.author_path : [{ kind: 'agent' as const, name: entry.peer || '', agent_id: null }];
    const last = path[path.length - 1];
    const agentId = typeof last?.agent_id === 'number' ? last.agent_id : byUuid;
    return { key: `from:${uuid ?? agentId ?? last?.name ?? ''}`, dir: 'from', path, agentId, sessionUuid: uuid, owner: false };
  }
  const head = headOf(entry);
  const author = head?.path[head.path.length - 1];
  if (!head || !author) return null;
  if (author.kind === 'owner') return { key: 'owner', dir: null, path: head.path, agentId: null, sessionUuid: null, owner: true };
  const agentId = typeof author.agent_id === 'number' ? author.agent_id : null;
  if (agentId !== null && agentId === self.id) {
    const own: AuthorCrumb = { kind: author.kind === 'sysop' ? 'sysop' : 'agent', name: self.name || author.name, agent_id: agentId };
    return { key: `self:${agentId}`, dir: null, path: [...head.path.slice(0, -1), own], agentId, sessionUuid: null, owner: false };
  }
  return { key: `from:${author.kind}:${agentId ?? author.name}`, dir: 'from', path: head.path, agentId, sessionUuid: null, owner: false };
}

export function chatRows(entries: readonly SwarmEntry[], self: ChatSelf, look: PartyLookup = {}): ChatRow[] {
  const rows: ChatRow[] = [];
  let quiet: SwarmEntry[] = [];
  let last: string | null = null;
  const flush = (): void => {
    const [lone] = quiet;
    if (quiet.length > 1 && lone) rows.push({ kind: 'fold', id: `fold:${lone.id}`, entries: quiet });
    else if (lone) rows.push({ kind: 'entry', entry: lone, party: null, first: true, at: lone.at });
    quiet = [];
  };
  for (const entry of entries) {
    if (isQuiet(entry)) {
      quiet.push(entry);
      last = null;
      continue;
    }
    flush();
    const party = partyOf(entry, self, look);
    const needs = needsOwner(entry) || questionOf(entry) !== null;
    const first = !party || needs || party.key !== last;
    rows.push({ kind: 'entry', entry, party, first, at: headOf(entry)?.at ?? entry.at });
    last = party && !needs ? party.key : null;
  }
  flush();
  return rows;
}

export interface ChatMenuExtra {
  key: string;
  label: string;
  run: () => void;
}

export interface ChatQuote {
  entryId: string;
  text: string;
  item: HuddleItem | null;
}

const QUOTE_MAX = 280;

export function quoteOf(entry: SwarmEntry): ChatQuote {
  const words = entry.kind === 'card' ? entry.item.text : fallbackText(entry);
  const flat = words.replace(/\s+/g, ' ').trim();
  const text = flat.length > QUOTE_MAX ? `${flat.slice(0, QUOTE_MAX - 3)}...` : flat;
  return { entryId: entry.id, text, item: entry.kind === 'card' && needsOwner(entry) ? entry.item : null };
}

export function quotedOrder(quote: ChatQuote, reply: string): string {
  return `> ${quote.text}\n\n${reply}`;
}
