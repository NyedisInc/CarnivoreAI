import { sessions } from '../api';
import type { SessionInfo } from '../api/types';
import { rowFor } from '../cells/terminal-viewer/meta';
import { PRIMARY_SLOT } from '../engine/model';
import { sessionForSlot } from '../engine/slot-identity';
import { primarySessionId, primaryTmuxName } from '../api/host';

export function displayName(label: string | null | undefined, tmuxName: string | null | undefined): string {
  const resolver = (globalThis as {
    SessionLabel?: { resolve(row: { label: string | null; name: string | null }): string | null };
  }).SessionLabel;
  const resolved = resolver
    ? resolver.resolve({ label: label ?? null, name: tmuxName ?? null })
    : (label ?? '').trim() || (tmuxName ?? '');
  return (resolved ?? '').trim();
}

export function nameForTab(tab: string): string {
  const id = tab === PRIMARY_SLOT ? primarySessionId() : sessionForSlot(tab, sessions.data);
  const row = rowFor(sessions.data, id);
  return displayName(row?.label, row?.tmux_session) || id;
}

export function liveRowFor(rowId: number | null): SessionInfo | null {
  if (rowId === null) return null;
  return (sessions.data ?? []).find((row) => row.session_row_id === rowId) ?? null;
}

export function rowIdForSession(sessionId: string): number | null {
  const found = rowFor(sessions.data, sessionId)?.session_row_id;
  return typeof found === 'number' && Number.isFinite(found) ? found : null;
}

export function primaryRowId(): number | null {
  const byId = rowIdForSession(primarySessionId());
  if (byId !== null) return byId;
  const tmux = primaryTmuxName();
  const found = tmux ? (sessions.data ?? []).find((row) => row.tmux_session === tmux)?.session_row_id : null;
  return typeof found === 'number' && Number.isFinite(found) ? found : null;
}

export function urlSlug(tmuxName: string): string {
  const lp = (globalThis as { Launchpad?: { _deriveRunningSessionDisplayName?: (n: string) => string } }).Launchpad;
  const derive = lp?._deriveRunningSessionDisplayName;
  return typeof derive === 'function' ? String(derive(tmuxName) ?? tmuxName) : tmuxName;
}
