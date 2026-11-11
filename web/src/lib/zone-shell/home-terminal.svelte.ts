import { untrack } from 'svelte';
import { asleep, sessions } from '../../opscenter/api';
import type { SessionInfo, SessionRecord } from '../../opscenter/api/types';
import { rowIdOfSlot } from '../../opscenter/engine/slot-identity';
import { t } from '../i18n/index.svelte';
import { browserCreateHost } from '../launchpad/create-host';
import { createConsoleFlow } from '../launchpad/create-flow';

export const HOME_SHELL_NAME = 'home-terminal';

const HOME_SHELL_TMUX = /^(?:carnivore|cloude)_home-terminal(?:-\d+)?$/;

const claims = new Map<string, number>();

let chain: Promise<unknown> = Promise.resolve();

export function targetGone(target: string | null, rows: readonly SessionInfo[], sleeping: readonly SessionRecord[]): boolean {
  if (!target) return true;
  const rowId = rowIdOfSlot(`terminal:${target}`);
  if (rowId === null) return !rows.some((row) => row.session?.id === target);
  if (rows.some((row) => row.session_row_id === rowId)) return false;
  return !sleeping.some((rec) => rec.id === rowId && rec.asleep !== false);
}

export function pickHomeShell(rows: readonly SessionInfo[], held: ReadonlySet<number>): number | null {
  const ids = rows
    .filter((row) => row.agent_family === 'shell' && HOME_SHELL_TMUX.test(row.tmux_session ?? ''))
    .map((row) => row.session_row_id)
    .filter((id): id is number => typeof id === 'number' && !held.has(id));
  return ids.length ? Math.min(...ids) : null;
}

async function createHomeShell(): Promise<string | null> {
  const host = { ...browserCreateHost(), announceSessionCreated: () => {} };
  const made = await createConsoleFlow(host, t, '~', { sessionName: HOME_SHELL_NAME, quiet: true });
  const id = typeof made.session?.id === 'string' ? made.session.id : '';
  if (made.outcome !== 'created' || !id) return null;
  await sessions.refresh(true);
  const rowId = (sessions.data ?? []).find((row) => row.session?.id === id)?.session_row_id;
  return typeof rowId === 'number' ? `row:${rowId}` : id;
}

export interface HomeTerminal {
  readonly target: string | null;
  readonly pending: boolean;
  readonly failed: boolean;
  retry(): void;
}

export function useHomeTerminal(input: () => { active: boolean; target: string | null; claimKey: string }): HomeTerminal {
  let bound = $state<string | null>(null);
  let failed = $state(false);
  let tries = $state(0);
  let busy = false;

  const decided = $derived(input().active && sessions.status === 'ok' && asleep.status === 'ok');
  const gone = $derived(decided && targetGone(input().target, sessions.data ?? [], asleep.data ?? []));
  const boundGone = $derived(bound !== null && decided && targetGone(bound, sessions.data ?? [], asleep.data ?? []));

  $effect(() => {
    if (untrack(() => input().active && asleep.status !== 'ok')) void asleep.refresh(true);
  });

  async function bind(key: string): Promise<void> {
    const held = new Set([...claims].filter(([other]) => other !== key).map(([, row]) => row));
    const picked = pickHomeShell(sessions.data ?? [], held);
    const target = picked !== null ? `row:${picked}` : await createHomeShell();
    if (target === null) { failed = true; return; }
    const rowId = rowIdOfSlot(`terminal:${target}`);
    if (rowId !== null) claims.set(key, rowId);
    bound = target;
  }

  $effect(() => {
    void tries;
    if (!gone || (bound !== null && !boundGone) || busy) return;
    const key = untrack(() => input().claimKey);
    busy = true;
    failed = false;
    chain = chain.then(() => bind(key)).catch((error: unknown) => {
      console.error('CloudeOpscenter: the terminal widget could not open its home shell', error);
      failed = true;
    }).finally(() => { busy = false; });
  });

  $effect(() => {
    const key = input().claimKey;
    return () => { claims.delete(key); };
  });

  return {
    get target() { return gone ? bound : input().target; },
    get pending() {
      if (gone) return !failed && (bound === null || boundGone);
      return input().active && !input().target && !decided;
    },
    get failed() { return gone && failed; },
    retry() { failed = false; tries += 1; },
  };
}
