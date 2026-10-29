
import { metaFor } from '../../engine/meta';
import type { SessionInfo } from '../../api';
import { autoSleep, type AutoSleepState } from '../../../lib/auto-sleep/auto-sleep-store.svelte';

export const meta = metaFor('keep-awake');

export interface KeptRow {
  name: string;
  info: SessionInfo | null;
}

export interface KeptView {
  rows: KeptRow[];
  total: number;
  unnamed: number;
  macAwake: boolean;
}

export function keptView(state: AutoSleepState, live: readonly SessionInfo[]): KeptView {
  const byName = new Map<string, SessionInfo>();
  for (const info of live) if (info.tmux_session) byName.set(info.tmux_session, info);
  const rows = state.keep_awake.map((name) => ({ name, info: byName.get(name) ?? null }));
  const total = state.keep_awake_session_uuids.length;
  return { rows, total, unnamed: Math.max(0, total - rows.length), macAwake: state.mac_awake };
}

export function titleCount(): number | null {
  if (autoSleep.status !== 'ok' || !autoSleep.data) return null;
  return autoSleep.data.keep_awake_session_uuids.length;
}

export function phoneTotal(): number | null {
  if (autoSleep.status !== 'ok' || !autoSleep.data) return null;
  return autoSleep.data.keep_awake.length;
}
