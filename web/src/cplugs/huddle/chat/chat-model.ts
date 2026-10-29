import type { HuddleItem } from '../huddle-model';
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
  return entry.waits_on_owner === true && !decisionOf(entry.item);
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

export function cardLineId(entry: { kind: string; event?: string; ref?: string }): number | null {
  if (entry.kind !== 'event' || entry.event !== 'card') return null;
  const found = /^card:([1-9][0-9]*)$/.exec(entry.ref ?? '');
  return found ? Number(found[1]) : null;
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

export function draws(entry: SwarmEntry): boolean {
  switch (entry.kind) {
    case 'card':
    case 'traffic':
      return true;
    case 'event':
      return !!textField(entry, 'text');
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

export type Direction = 'from' | null;

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
  return entry.kind === 'event';
}

function selfParty(self: ChatSelf, own: AuthorCrumb, path: AuthorCrumb[] = []): BurstParty {
  return { key: `self:${self.id}`, dir: null, path: [...path, own], agentId: self.id, sessionUuid: null, owner: false };
}

export function recipientOf(entry: SwarmEntry, look: PartyLookup = {}): BurstParty | null {
  if (entry.kind !== 'traffic' || entry.direction !== 'out') return null;
  const uuid = entry.peer_session_uuid || null;
  const agentId = (uuid ? (look.idOfUuid?.(uuid) ?? null) : null) ?? (entry.peer ? (look.idOfName?.(entry.peer) ?? null) : null);
  const name = entry.peer || '';
  return { key: `to:${uuid ?? agentId ?? name}`, dir: null, path: [{ kind: 'agent', name, agent_id: agentId }], agentId, sessionUuid: uuid, owner: false };
}

export function partyOf(entry: SwarmEntry, self: ChatSelf, look: PartyLookup = {}): BurstParty | null {
  if (entry.kind === 'traffic') {
    if (entry.direction === 'out') return selfParty(self, { kind: 'agent', name: self.name, agent_id: self.id });
    const uuid = entry.peer_session_uuid || null;
    const byUuid = uuid ? (look.idOfUuid?.(uuid) ?? null) : null;
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
    return selfParty(self, own, head.path.slice(0, -1));
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

export function awaitingReply(entries: readonly SwarmEntry[]): boolean {
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const kind = entries[i]?.kind;
    if (kind === 'owner') return true;
    if (kind === 'agent' || kind === 'card') return false;
  }
  return false;
}

export const COMPOSER_MAX_LINES = 10;
export const COMPOSER_MAX_SHARE = 0.4;

export function composerCap(line: number, chrome: number, room: number): number {
  const rest = 2 * line + chrome;
  return Math.max(rest, Math.min(COMPOSER_MAX_LINES * line + chrome, COMPOSER_MAX_SHARE * room));
}

export function composerGhost(draft: string, suggestion: string | null | undefined): string {
  return draft === '' && suggestion ? suggestion : '';
}

export function tabAccepts(key: string, draft: string, suggestion: string | null | undefined): string | null {
  const ghost = composerGhost(draft, suggestion);
  return key === 'Tab' && ghost ? ghost : null;
}
