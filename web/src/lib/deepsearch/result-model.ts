import type { DeepGroup, DeepHit } from './deepsearch-api';

export type Layout = 'ledger' | 'best';
export const LAYOUTS: readonly Layout[] = ['ledger', 'best'];
export const DEFAULT_LAYOUT: Layout = 'ledger';
export const LAYOUT_KEY = 'carnivore.deepsearch.layout';

export const HITS_COLLAPSED = 2;
export const NAME_CHARS = 80;

export type Tr = (key: string, params?: Record<string, string | number>) => string;

export type ConvState = 'live' | 'asleep' | 'none' | 'backup' | 'computer';

export interface LiveRow {
  activity_status?: string | null;
  label?: string | null;
}

type StorageRead = Pick<Storage, 'getItem'>;
type StorageWrite = Pick<Storage, 'setItem'>;

function browserStorage(): Storage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function readLayout(storage: StorageRead | null = browserStorage()): Layout {
  try {
    const stored = storage?.getItem(LAYOUT_KEY);
    return stored === 'ledger' || stored === 'best' ? stored : DEFAULT_LAYOUT;
  } catch {
    return DEFAULT_LAYOUT;
  }
}

export function writeLayout(layout: Layout, storage: StorageWrite | null = browserStorage()): void {
  try {
    storage?.setItem(LAYOUT_KEY, layout);
  } catch {
  }
}

export function isRemote(group: DeepGroup): boolean {
  return group.hostKey !== null && group.hostKey !== 'local';
}

export function oneLine(text: string | null, max: number): string {
  const flat = (text ?? '').split(/\s+/).filter(Boolean).join(' ');
  return flat.length > max ? `${flat.slice(0, max).trimEnd()}...` : flat;
}

const BARE_ID = /^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{16,})$/i;

function lastFolder(path: string | null): string {
  return path?.split('/').filter(Boolean).pop() ?? '';
}

export function conversationName(group: DeepGroup, liveLabel: string | null | undefined, tr: Tr): string {
  const rungs = [liveLabel?.trim() ?? '', group.session?.trim() ?? '', oneLine(group.firstPrompt, NAME_CHARS), lastFolder(group.workingDir)];
  return rungs.find((name) => name !== '' && !BARE_ID.test(name)) ?? tr('deepsearch.untitled');
}

export function conversationState(group: DeepGroup, live: LiveRow | undefined): ConvState {
  if (isRemote(group)) return 'computer';
  if (group.hits.some((h) => h.fromBackup)) return 'backup';
  if (live && live.activity_status !== 'dead') return 'live';
  return group.sessionUuid ? 'asleep' : 'none';
}

export type LedKind = 'live' | 'ring' | 'dash';

export function ledKind(state: ConvState, group: DeepGroup): LedKind {
  if (state === 'live') return 'live';
  if (state === 'asleep' || (state === 'backup' && group.sessionUuid !== null)) return 'ring';
  return 'dash';
}

export const stateKey = (state: ConvState): string => `deepsearch.state.${state}`;

const dayNumber = (d: Date): number => Math.floor(new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 86_400_000);

function dateLabel(at: Date, now: Date): string {
  const day = at.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toLowerCase();
  return at.getFullYear() === now.getFullYear() ? day : `${day} ${at.getFullYear()}`;
}

function parse(iso: string | null): Date | null {
  const at = iso ? new Date(iso) : null;
  return at && !Number.isNaN(at.getTime()) ? at : null;
}

export function relativeWhen(iso: string | null, now: Date, tr: Tr): string {
  const at = parse(iso);
  if (!at) return '';
  const days = dayNumber(now) - dayNumber(at);
  const minutes = Math.floor((now.getTime() - at.getTime()) / 60_000);
  if (days <= 0) {
    if (minutes < 1) return tr('deepsearch.when.now');
    return minutes < 60 ? tr('deepsearch.when.minutes', { n: minutes }) : tr('deepsearch.when.hours', { n: Math.floor(minutes / 60) });
  }
  return days === 1 ? tr('deepsearch.when.yesterday') : dateLabel(at, now);
}

export function hitClock(iso: string | null, now: Date): string {
  const at = parse(iso);
  if (!at) return '';
  if (dayNumber(now) !== dayNumber(at)) return dateLabel(at, now);
  return `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`;
}

export function visibleHits(group: DeepGroup, expanded: boolean): DeepHit[] {
  return expanded ? group.hits : group.hits.slice(0, HITS_COLLAPSED);
}

export function hiddenCount(group: DeepGroup, expanded: boolean): number {
  const shown = visibleHits(group, expanded).length;
  return Math.max(0, (isRemote(group) ? group.hits.length : group.matches) - shown);
}

export function needsFetch(group: DeepGroup): boolean {
  return !isRemote(group) && group.matches > group.hits.length;
}

export interface WalkedHit {
  index: number;
  group: DeepGroup;
  hit: DeepHit;
}

export function walk(groups: readonly DeepGroup[], expanded: Readonly<Record<string, true>>): WalkedHit[] {
  let index = 0;
  return groups.flatMap((group) => visibleHits(group, expanded[group.conversationId] === true).map((hit) => ({ index: index++, group, hit })));
}

export function startIndexes(groups: readonly DeepGroup[], expanded: Readonly<Record<string, true>>): Record<string, number> {
  const out: Record<string, number> = {};
  let n = 0;
  for (const group of groups) {
    out[group.conversationId] = n;
    n += visibleHits(group, expanded[group.conversationId] === true).length;
  }
  return out;
}

export function countLine(matches: number, conversations: number, tr: Tr): string {
  const hits = tr(matches === 1 ? 'deepsearch.hits_one' : 'deepsearch.hits_many', { count: matches });
  const convs = tr(conversations === 1 ? 'deepsearch.conversations_one' : 'deepsearch.conversations_many', { count: conversations });
  return tr('deepsearch.count', { hits, conversations: convs });
}

export function staleLine(n: number, tr: Tr): string {
  return n <= 0 ? '' : tr(n === 1 ? 'deepsearch.stale_one' : 'deepsearch.stale_many', { count: n });
}

export type ActionId = 'read' | 'go' | 'resume' | 'branch' | 'link' | 'bookmark' | 'scope' | 'closest';

export function hitActions(state: ConvState, group: DeepGroup, hit: DeepHit): ActionId[] {
  const out: ActionId[] = [];
  const anchored = hit.line !== null;
  if (anchored) out.push('read');
  const bound = (state === 'live' || state === 'asleep') && group.sessionUuid !== null;
  if (bound) out.push(state === 'live' ? 'go' : 'resume');
  if (bound && hit.entryUuid !== null) out.push('branch');
  if (anchored) out.push('link');
  if (bound && hit.entryUuid !== null) out.push('bookmark');
  if (bound) out.push('scope');
  if (hit.bookmark !== null && anchored) out.push('closest');
  return out;
}

export function splitActions(ids: readonly ActionId[]): { strip: ActionId[]; menu: ActionId[] } {
  const stripIds: readonly ActionId[] = ['read', 'go', 'resume', 'link'];
  return { strip: ids.filter((id) => stripIds.includes(id)), menu: ids.filter((id) => !stripIds.includes(id)) };
}
