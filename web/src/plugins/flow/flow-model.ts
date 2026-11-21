
export type FeedKind = 'bubble' | 'work' | 'crosstalk' | 'spawn' | 'launch' | 'return' | 'huddle' | 'task';

export const RANK: Record<FeedKind, number> = { crosstalk: 0, spawn: 0, launch: 0, huddle: 1, task: 1, bubble: 2, work: 3, return: 4 };

export interface FeedLane {
  id: string;
  kind: 'session' | 'subagent' | 'owner' | string;
  label: string;
  parent: string | null;
  depth: number;
  color: number | null;
}

export interface WorkCall {
  tool: string;
  start: number;
  end: number;
}

export interface FeedItem {
  id: string;
  kind: FeedKind;
  lane: string;
  t: number;
  u: number;
  to?: string;
  role?: 'agent' | 'prompt' | 'task' | string;
  text?: string;
  label?: string;
  inferred?: boolean;
  count?: number;
  tools?: Record<string, number>;
  duration_s?: number | null;
  calls?: WorkCall[];
  thread?: string | null;
  reply_to?: string | null;
  delivered?: boolean;
  landed?: boolean;
  basis?: string | null;
  status?: string | null;
  tool_count?: number | null;
  item_id?: number | null;
  owner?: boolean;
  change?: 'filed' | 'moved' | string;
  from_col?: string | null;
  to_col?: string | null;
}

export interface FeedAnswer {
  seed: { kind: string; id: string; title?: string };
  window: { start: number; end: number };
  lanes: FeedLane[];
  items: FeedItem[];
  cursor: number;
  total: number;
  full: boolean;
  warnings: string[];
}

export interface FeedHeld {
  byId: Map<string, FeedItem>;
  ordered: FeedItem[];
  lanes: Map<string, FeedLane>;
  cursor: number | null;
  windowStart: number | null;
}

export function emptyFeed(): FeedHeld {
  return { byId: new Map(), ordered: [], lanes: new Map(), cursor: null, windowStart: null };
}

export function compareItems(a: FeedItem, b: FeedItem): number {
  return a.t - b.t || RANK[a.kind] - RANK[b.kind] || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

function num(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function parseItems(raw: unknown): FeedItem[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((i): i is FeedItem => !!i && typeof i === 'object' && typeof i.id === 'string' && typeof i.lane === 'string'
    && Object.prototype.hasOwnProperty.call(RANK, i.kind) && num(i.t) && num(i.u));
}

export function mergeFeed(held: FeedHeld, answer: FeedAnswer): { resync: boolean; added: string[] } {
  if (answer.full) held.byId.clear();
  const added: string[] = [];
  for (const item of parseItems(answer.items)) {
    if (!held.byId.has(item.id)) added.push(item.id);
    held.byId.set(item.id, item);
  }
  held.ordered = [...held.byId.values()].sort(compareItems);
  held.lanes = new Map((answer.lanes ?? []).map((lane) => [lane.id, lane]));
  held.cursor = num(answer.cursor) ? answer.cursor : held.cursor;
  if (held.windowStart === null && num(answer.window?.start)) held.windowStart = answer.window.start;
  return { resync: held.byId.size > answer.total, added };
}

export interface FlowSeed {
  kind: 'huddle_item' | 'session';
  id: string;
}

export function feedItemIds(seed: FlowSeed, items: readonly FeedItem[]): Set<number> {
  const ids = new Set<number>();
  if (seed.kind === 'huddle_item' && /^[1-9][0-9]*$/.test(seed.id)) ids.add(Number(seed.id));
  for (const item of items) if (typeof item.item_id === 'number') ids.add(item.item_id);
  return ids;
}

export const ITEM_PARAM = 'item';
export const SESSION_PARAM = 'session';

export function seedFromSearch(search: string): FlowSeed | null {
  const params = new URLSearchParams(search);
  const item = params.get(ITEM_PARAM)?.trim().replace(/^#/, '') ?? '';
  if (/^[1-9][0-9]{0,9}$/.test(item)) return { kind: 'huddle_item', id: item };
  const session = params.get(SESSION_PARAM)?.trim() ?? '';
  return session && session.length <= 200 ? { kind: 'session', id: session } : null;
}

export function feedPath(seed: FlowSeed, held: FeedHeld): string {
  const query = new URLSearchParams({ seed: seed.kind, id: seed.id });
  if (held.windowStart !== null) query.set('start', String(held.windowStart));
  if (held.cursor !== null) query.set('cursor', String(held.cursor));
  return `/cplugs/flow/feed?${query.toString()}`;
}

export function clockTime(seconds: number): string {
  const d = new Date(seconds * 1000);
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':');
}

export function shortDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export function laneColor(color: number | null): string {
  return color === null ? 'var(--oc-text-secondary)' : `var(--oc-series-${(color % 8) + 1})`;
}
