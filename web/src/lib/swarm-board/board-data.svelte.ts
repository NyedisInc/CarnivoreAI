import { authFetch, ApiError } from '../../opscenter/api/auth.svelte';
import { resourcePush } from '../resource-push/boot';
import { familyOf } from '../resource-push/store';
import { floorSource } from '../../cplugs/sdk';
import { swarmRoster, startSwarmRoster, type RosterAgent } from '../../cplugs/huddle/agents/agent-roster.svelte';
import { colorBook, type ColorBook } from '../../cplugs/huddle/swarm/agent-colors.svelte';
import type { NodeLooks } from '../../cplugs/huddle/swarm/node-look';
import { createNodeLooks } from '../../cplugs/huddle/swarm/node-looks.svelte';
import { COLUMNS, scopeParam, type BoardQuery, type CardBoard, type CardColumn, type CardLane, type CardView } from './board-types';

export const CARDS_FAMILY = 'cplug.huddle.cards';
export const BOARD_FALLBACK_POLL_MS = 15000;
const COALESCE_MS = 150;
export const DONE_LIMIT = 100;
const CLOCK_MS = 60000;

export type BoardStatus = 'loading' | 'ok' | 'error' | 'off';

export interface BoardLane extends CardLane {
  companyId: number | null;
  companyName: string | null;
  owner: RosterAgent | null;
}

export interface BoardData {
  readonly status: BoardStatus;
  readonly error: string | null;
  readonly board: CardBoard | null;
  readonly lanes: readonly BoardLane[];
  readonly search: string;
  readonly archived: 'hide' | 'only';
  readonly agents: readonly RosterAgent[];
  readonly looks?: NodeLooks;
  readonly colors: ColorBook;
  readonly now: number;
  agent(id: number | null | undefined): RosterAgent | undefined;
  refresh(): Promise<void>;
}

export function cardMatches(card: Pick<CardView, 'id' | 'title'>, q: string): boolean {
  if (!q) return true;
  if (q.startsWith('#')) return String(card.id) === q.slice(1) || String(card.id).startsWith(q.slice(1));
  return card.title.toLowerCase().includes(q) || String(card.id) === q;
}

export function shapeLanes(
  board: CardBoard | null,
  q: string,
  companyOf: (projectId: number | null) => { id: number; name: string } | null,
  ownerOf: (lane: CardLane) => RosterAgent | null,
): BoardLane[] {
  if (!board) return [];
  const out: BoardLane[] = [];
  for (const lane of board.lanes) {
    let columns = lane.columns;
    let counts = lane.counts;
    if (q) {
      columns = Object.fromEntries(COLUMNS.map((c) => [c, (lane.columns[c] ?? []).filter((card) => cardMatches(card, q))])) as Record<CardColumn, CardView[]>;
      counts = Object.fromEntries(COLUMNS.map((c) => [c, columns[c].length])) as Record<CardColumn, number>;
      if (COLUMNS.every((c) => counts[c] === 0)) continue;
    }
    const company = companyOf(lane.project_id);
    out.push({ ...lane, columns, counts, companyId: company?.id ?? null, companyName: company?.name ?? null, owner: ownerOf(lane) });
  }
  return out;
}

export function laneOwner(lane: Pick<CardLane, 'project_id' | 'list_key'>, agents: readonly RosterAgent[]): RosterAgent | null {
  if (lane.project_id !== null) return agents.find((a) => a.rank === 'project' && a.project_id === lane.project_id) ?? null;
  return agents.find((a) => a.thread_key === lane.list_key) ?? null;
}

export function createBoardData(query: () => BoardQuery, search: () => string): BoardData {
  let board = $state<CardBoard | null>(null);
  let status = $state<BoardStatus>('loading');
  let error = $state<string | null>(null);
  let now = $state(Date.now());
  let wanted = '';
  let reading = false;
  let again = false;
  let pending: ReturnType<typeof setTimeout> | null = null;

  async function read(): Promise<void> {
    if (reading) {
      again = true;
      return;
    }
    reading = true;
    const asked = wanted;
    try {
      const answer = await authFetch<CardBoard>(`/swarm/cards/board?${asked}`);
      if (asked === wanted) {
        board = answer;
        status = 'ok';
        error = null;
        now = Date.now();
      }
    } catch (failure) {
      if (asked === wanted) {
        const off = failure instanceof ApiError && failure.status === 409 && failure.code === 'cards_off';
        status = off ? 'off' : 'error';
        error = failure instanceof Error ? failure.message : String(failure);
        if (off) board = null;
      }
    } finally {
      reading = false;
    }
    if (again || asked !== wanted) {
      again = false;
      await read();
    }
  }

  function schedule(): void {
    if (pending) return;
    pending = setTimeout(() => {
      pending = null;
      void read();
    }, COALESCE_MS);
  }

  $effect(() => {
    const q = query();
    const next = new URLSearchParams({ scope: scopeParam(q.scope), filter: q.filter, done_limit: String(DONE_LIMIT), archived: q.archived ?? 'hide' }).toString();
    if (next === wanted) return;
    if (board && board.scope !== scopeParam(q.scope)) status = 'loading';
    wanted = next;
    void read();
  });

  $effect(() => {
    const push = resourcePush();
    const off = push.onChange((topics) => {
      if (topics.some((t) => familyOf(t) === CARDS_FAMILY)) schedule();
    });
    const stopPoll = push.pushOrPoll(schedule, BOARD_FALLBACK_POLL_MS, [CARDS_FAMILY]);
    return () => {
      off();
      stopPoll();
      if (pending) clearTimeout(pending);
      pending = null;
    };
  });

  $effect(() => startSwarmRoster());

  $effect(() => {
    const clock = setInterval(() => (now = Date.now()), CLOCK_MS);
    return () => clearInterval(clock);
  });

  const source = $derived(floorSource());
  const colors = $derived(colorBook(swarmRoster.agents, source));
  const looks = createNodeLooks();
  const companyOf = (projectId: number | null): { id: number; name: string } | null => {
    if (projectId === null) return null;
    const companyId = source.projects.find((p) => p.id === projectId)?.companyId ?? null;
    const company = companyId === null ? undefined : source.companies.find((c) => c.id === companyId);
    return company ? { id: company.id, name: company.name } : null;
  };
  const q = $derived(search().trim().toLowerCase());
  const lanes = $derived(shapeLanes(board, q, companyOf, (lane) => laneOwner(lane, swarmRoster.agents)));

  return {
    get status() { return status; },
    get error() { return error; },
    get board() { return board; },
    get lanes() { return lanes; },
    get search() { return q; },
    get archived() { return query().archived ?? 'hide'; },
    get agents() { return swarmRoster.agents; },
    get colors() { return colors; },
    looks,
    get now() { return now; },
    agent: (id) => (id === null || id === undefined ? undefined : swarmRoster.agents.find((a) => a.id === id)),
    refresh: () => read(),
  };
}

export type { RosterAgent };
