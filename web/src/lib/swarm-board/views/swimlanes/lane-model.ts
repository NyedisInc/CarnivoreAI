import { COLUMNS, type CardColumn, type CardCounts, type CardView } from '../../board-types';
import type { BoardLane, RosterAgent } from '../../board-data.svelte';

export const CELL_CARDS = 5;
export const MAX_FACES = 4;
export const FOLDS_KEY = 'carnivore.swarm-board.folds';
export const CHAT_KEY = 'carnivore.swarm-board.chat';

export function laneTotal(counts: CardCounts): number {
  return COLUMNS.reduce((n, c) => n + (counts[c] ?? 0), 0);
}

export function isQuiet(counts: CardCounts): boolean {
  return (counts.in_progress ?? 0) + (counts.review ?? 0) === 0;
}

export function orderLanes(lanes: readonly BoardLane[]): BoardLane[] {
  const shown = lanes.filter((l) => laneTotal(l.counts) > 0);
  return [...shown.filter((l) => !isQuiet(l.counts)), ...shown.filter((l) => isQuiet(l.counts))];
}

export interface LaneFace {
  agent: RosterAgent;
  working: boolean;
}

function standIn(id: number, name: string | null): RosterAgent {
  return { id, display_name: name ?? `#${id}`, rank: 'task', state: 'asleep', thread_key: `agent:${id}` };
}

export function laneFaces(lane: BoardLane, agentOf: (id: number) => RosterAgent | undefined): LaneFace[] {
  const faces: LaneFace[] = [];
  const seen = new Set<number>();
  for (const card of lane.columns.in_progress ?? []) {
    const id = card.holder?.agent_id;
    if (id === undefined || seen.has(id)) continue;
    seen.add(id);
    faces.push({ agent: agentOf(id) ?? standIn(id, card.holder?.name ?? null), working: true });
  }
  if (lane.owner && !seen.has(lane.owner.id)) faces.push({ agent: lane.owner, working: false });
  return faces;
}

export interface RollupSegment {
  column: CardColumn;
  count: number;
}

export function rollup(counts: CardCounts): RollupSegment[] {
  return COLUMNS.filter((c) => (counts[c] ?? 0) > 0).map((c) => ({ column: c, count: counts[c] }));
}

export function cellCards(cards: readonly CardView[], count: number, open: boolean): { shown: CardView[]; more: number } {
  if (open) return { shown: [...cards], more: 0 };
  const shown = cards.slice(0, CELL_CARDS);
  return { shown, more: Math.max(0, count - shown.length) };
}

export function readFolds(): Record<string, boolean> {
  try {
    const raw = globalThis.localStorage?.getItem(FOLDS_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).filter((e): e is [string, boolean] => typeof e[1] === 'boolean'));
  } catch {
    return {};
  }
}

export function writeFolds(folds: Record<string, boolean>): void {
  try {
    globalThis.localStorage?.setItem(FOLDS_KEY, JSON.stringify(folds));
  } catch {
  }
}

export function isFolded(lane: Pick<BoardLane, 'list_key' | 'counts'>, folds: Record<string, boolean>, archived = false): boolean {
  return folds[lane.list_key] ?? (!archived && isQuiet(lane.counts));
}

export function readChatColumn(): boolean {
  try {
    return globalThis.localStorage?.getItem(CHAT_KEY) === '1';
  } catch {
    return false;
  }
}

export function writeChatColumn(on: boolean): void {
  try {
    if (on) globalThis.localStorage?.setItem(CHAT_KEY, '1');
    else globalThis.localStorage?.removeItem(CHAT_KEY);
  } catch {
  }
}
