import { authFetch, ApiError } from '../../../../opscenter/api/auth.svelte';
import type { BoardData } from '../../board-data.svelte';

export interface CardEventRow {
  item_id: number;
  list_key: string;
  at: number;
  kind: string;
  from_col: string;
  to_col: string;
  by: string;
}

export interface CardEventAnswer {
  scope: string;
  filter: string;
  since: number;
  until: number;
  events: CardEventRow[];
  truncated: boolean;
}

export interface EventRange {
  since: number;
  until: number;
}

export interface CardEventWindow {
  readonly status: 'loading' | 'ok' | 'error';
  readonly error: string | null;
  readonly rows: readonly CardEventRow[];
  readonly truncated: boolean;
}

export function fetchCardEvents(scope: string, filter: string, range: EventRange): Promise<CardEventAnswer> {
  const q = new URLSearchParams({ scope, filter, since: String(range.since), until: String(range.until) });
  return authFetch<CardEventAnswer>(`/swarm/cards/events?${q.toString()}`);
}

export function createEventWindow(data: BoardData, range: () => EventRange | null): CardEventWindow {
  let rows = $state<CardEventRow[]>([]);
  let truncated = $state(false);
  let status = $state<'loading' | 'ok' | 'error'>('loading');
  let error = $state<string | null>(null);
  let wanted = '';
  let args: { scope: string; filter: string; range: EventRange } | null = null;
  let reading = false;
  let stale = false;
  let seen: unknown = null;

  async function read(): Promise<void> {
    if (reading) {
      stale = true;
      return;
    }
    reading = true;
    const asked = wanted;
    const ask = args;
    if (!ask) {
      reading = false;
      return;
    }
    try {
      const answer = await fetchCardEvents(ask.scope, ask.filter, ask.range);
      if (asked === wanted) {
        rows = answer.events;
        truncated = answer.truncated;
        status = 'ok';
        error = null;
      }
    } catch (failure) {
      if (asked === wanted) {
        status = 'error';
        error = failure instanceof ApiError || failure instanceof Error ? failure.message : String(failure);
      }
    } finally {
      reading = false;
    }
    if (stale || asked !== wanted) {
      stale = false;
      if (wanted) await read();
    }
  }

  $effect(() => {
    const board = data.board;
    const r = range();
    if (!board || !r) return;
    const next = `${board.scope}|${board.filter}|${r.since}|${r.until}`;
    if (next === wanted && board === seen) return;
    seen = board;
    if (next !== wanted) {
      if (wanted.split('|').slice(0, 2).join('|') !== next.split('|').slice(0, 2).join('|')) status = 'loading';
      wanted = next;
      args = { scope: board.scope, filter: board.filter, range: { since: r.since, until: r.until } };
    }
    void read();
  });

  $effect(() => () => {
    wanted = '';
    args = null;
  });

  return {
    get status() { return status; },
    get error() { return error; },
    get rows() { return rows; },
    get truncated() { return truncated; },
  };
}
