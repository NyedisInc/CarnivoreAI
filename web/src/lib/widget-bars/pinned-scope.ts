import { sessions } from '../../opscenter/api';
import { asleep } from '../../opscenter/api/asleep.svelte';
import { recent } from '../../opscenter/api/recent.svelte';
import type { SessionRecord } from '../../opscenter/api/types';
import { activeTerminalSessionId } from '../../opscenter/lib/active-terminal';
import { displayName } from '../../opscenter/layouts/names';
import { scopeForWidget, sessionScopeFor, type ScopeRow, type SessionScope } from '../../opscenter/widgets/session-scope';
import type { WidgetManifest } from '../../opscenter/widgets/types';

export interface PinRow extends ScopeRow {
  label?: string | null;
  tmux_session?: string | null;
  activity_status?: string | null;
  host_state?: string | null;
}

export type PinAsleepRow = Pick<SessionRecord, 'session_uuid' | 'id' | 'title' | 'tmux_name' | 'working_dir' | 'project_id'>;

export interface PinnedAgent {
  state: 'live' | 'asleep' | 'stopped' | 'gone' | 'unknown';
  name: string;
  suffix: '' | 'asleep' | 'stopped' | 'disconnected';
  scope: SessionScope | null;
}

export interface PinnedAgent {
  state: 'live' | 'asleep' | 'stopped' | 'gone' | 'unknown';
  name: string;
  suffix: '' | 'asleep' | 'stopped' | 'disconnected';
  scope: SessionScope | null;
}

export function heldScope(row: number): SessionScope {
  return { sessionId: '', rowId: row, workingDir: '', projectId: null };
}

/* label: ' */
export function pinnedAgentFor(row: number, live: readonly PinRow[] | null, asleepRows: readonly PinAsleepRow[] | null, recentRows: readonly PinAsleepRow[] | null, complete: boolean): PinnedAgent {
  const unknown: PinnedAgent = { state: 'unknown', name: '', suffix: '', scope: null };
  const found = (live ?? []).find((info) => info.session_row_id === row);
  if (found?.session?.id) {
    const suffix = found.host_state === 'disconnected' ? 'disconnected' : found.activity_status === 'dead' ? 'stopped' : '';
    return { state: 'live', name: displayName(found.label, found.tmux_session), suffix, scope: sessionScopeFor(live, found.session.id) };
  }
  const sleeper = (asleepRows ?? []).find((record) => record.id === row);
  const stopped = sleeper ? undefined : (recentRows ?? []).find((record) => record.id === row);
  const stored = sleeper ?? stopped;
  if (stored) {
    const scope: SessionScope = { sessionId: stored.session_uuid, rowId: row, workingDir: stored.working_dir ?? '', projectId: stored.project_id ?? null };
    return { state: sleeper ? 'asleep' : 'stopped', name: displayName(stored.title, stored.tmux_name), suffix: sleeper ? 'asleep' : 'stopped', scope };
  }
  return complete && live !== null && asleepRows !== null && recentRows !== null ? { ...unknown, state: 'gone' } : unknown;
}

export function pinnedAgent(row: number): PinnedAgent {
  const recentOk = recent.status === 'ok' && recent.data?.state === 'ok';
  return pinnedAgentFor(row, sessions.data, asleep.data, recentOk ? recent.data!.sessions : null, sessions.status === 'ok' && asleep.status === 'ok' && recentOk);
}

export function pinnedScopeFor(manifest: Pick<WidgetManifest, 'scope'> | undefined, row: number): SessionScope | null {
  return scopeForWidget(manifest, pinnedAgent(row).scope);
}

export function activeAgent(): { row: number | null; name: string } {
  const info = (sessions.data ?? []).find((one) => one.session?.id === activeTerminalSessionId());
  return { row: typeof info?.session_row_id === 'number' ? info.session_row_id : null, name: displayName(info?.label, info?.tmux_session) };
}

const PREFIX = /^\p{L}{1,4}-/u;
const LETTER = /\p{L}/gu;
const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

export function nameLetters(name: string): string[] {
  const whole = name.trim();
  const stripped = whole.replace(PREFIX, '');
  const mine = (stripped.match(LETTER)?.length ? stripped : whole).match(LETTER) ?? [];
  return [...new Set(mine.map((one) => one.toLocaleUpperCase()))];
}

export function allocateLetters(prev: ReadonlyMap<number, string>, wanted: readonly { row: number; name: string }[]): Map<number, string> {
  const next = new Map<number, string>();
  for (const { row } of wanted) if (prev.has(row)) next.set(row, prev.get(row)!);
  const taken = new Set(next.values());
  for (const { row, name } of wanted) {
    if (next.has(row) || !name.trim()) continue;
    const pick = [...nameLetters(name), ...ALPHABET].find((one) => !taken.has(one));
    if (pick === undefined) continue;
    taken.add(pick);
    next.set(row, pick);
  }
  return next;
}
