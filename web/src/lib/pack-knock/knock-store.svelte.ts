import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';

export const KNOCK_TOPIC = 'pack_knocks';
export const KNOCKS_ROUTE = '/computers/knocks';
export const KNOCK_POLL_MS = 5000;
const HIDDEN_KEY = 'pack_knock_hidden';

export interface Knock {
  readonly id: string;
  readonly label: string;
  readonly addr: string;
  readonly fid_short: string;
  readonly code: string | null;
  readonly expires_at: string;
  readonly attempts_left: number;
}

export function parseKnocks(body: unknown): Knock[] {
  const rows = (body as { knocks?: unknown } | null)?.knocks;
  if (!Array.isArray(rows)) return [];
  return rows
    .filter((k) => !!k && typeof k.id === 'string' && typeof k.label === 'string' && typeof k.expires_at === 'string')
    .map((k): Knock => ({
      id: k.id,
      label: k.label,
      addr: typeof k.addr === 'string' ? k.addr : '',
      fid_short: typeof k.fid_short === 'string' ? k.fid_short : '',
      code: typeof k.code === 'string' ? k.code : null,
      expires_at: k.expires_at,
      attempts_left: typeof k.attempts_left === 'number' ? k.attempts_left : 0,
    }));
}

function loadHidden(): string | null {
  try {
    return sessionStorage.getItem(HIDDEN_KEY);
  } catch {
    return null;
  }
}

function saveHidden(id: string | null): void {
  try {
    if (id === null) sessionStorage.removeItem(HIDDEN_KEY);
    else sessionStorage.setItem(HIDDEN_KEY, id);
  } catch {
  }
}

const state = $state<{ hidden: string | null; started: boolean }>({ hidden: loadHidden(), started: false });
let knocks: Resource<Knock[]> | null = null;

export function startKnocks(): void {
  if (knocks) return;
  knocks = resource<Knock[]>(() => authFetch<unknown>(KNOCKS_ROUTE).then(parseKnocks), { intervalMs: KNOCK_POLL_MS, name: 'pack-knocks', topics: [KNOCK_TOPIC] });
  state.started = true;
}

export const pending = (): readonly Knock[] => (state.started ? knocks?.data : null) ?? [];

export const shown = (): Knock | null => pending().find((k) => k.id !== state.hidden) ?? null;

export function hide(id: string): void {
  state.hidden = id;
  saveHidden(id);
}

export async function reread(): Promise<void> {
  await knocks?.refresh(true);
}

export async function notMe(id: string): Promise<void> {
  hide(id);
  try {
    await authFetch(`${KNOCKS_ROUTE}/${encodeURIComponent(id)}`, { method: 'DELETE' });
  } finally {
    await reread();
  }
}
