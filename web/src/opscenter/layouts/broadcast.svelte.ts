import { sessions } from '../api';
import type { SessionInfo } from '../api/types';
import { layoutError, setMemberBroadcast, type LayoutMember } from './api';
import { layoutActive, layoutMode, memberForRow } from './mode.svelte';
import { displayName, liveRowFor, rowIdForSession } from './names';

const BUSY = new Set(['working', 'working_subagent']);

export function broadcastOn(member: LayoutMember): boolean {
  return member.broadcast !== false;
}

function setFlag(rowId: number, on: boolean): void {
  layoutMode.members = layoutMode.members.map((one) =>
    one.session_row_id === rowId ? { ...one, broadcast: on } : one);
}

export function syncBroadcastFlags(members: LayoutMember[]): void {
  const stored = new Map(members.map((one) => [one.session_row_id, broadcastOn(one)]));
  if (!layoutMode.members.some((one) => stored.has(one.session_row_id)
    && stored.get(one.session_row_id) !== broadcastOn(one))) return;
  layoutMode.members = layoutMode.members.map((one) =>
    stored.has(one.session_row_id) ? { ...one, broadcast: stored.get(one.session_row_id) } : one);
}

export async function toggleBroadcast(member: LayoutMember): Promise<string | null> {
  const uuid = layoutMode.uuid;
  const next = !broadcastOn(member);
  setFlag(member.session_row_id, next);
  try {
    const write = await setMemberBroadcast(uuid, member.session_uuid, next);
    if (layoutMode.uuid === uuid && write.layout) syncBroadcastFlags(write.layout.members);
    return null;
  } catch (error) {
    if (layoutMode.uuid === uuid) setFlag(member.session_row_id, !next);
    return layoutError(error).detail;
  }
}

export interface Recipients {
  receiving: number;
  total: number;
  busy: string[];
}

function live(row: SessionInfo | null): row is SessionInfo {
  return row !== null && row.activity_status !== 'dead';
}

export function recipients(): Recipients {
  void sessions.data;
  let receiving = 0;
  const busy: string[] = [];
  for (const member of layoutMode.members) {
    const row = liveRowFor(member.session_row_id);
    if (!broadcastOn(member) || !live(row)) continue;
    receiving += 1;
    if (BUSY.has(String(row.activity_status ?? ''))) busy.push(displayName(row.label, row.tmux_session));
  }
  return { receiving, total: layoutMode.members.length, busy };
}

export function memberName(member: LayoutMember): string {
  const row = liveRowFor(member.session_row_id);
  return (row ? displayName(row.label, row.tmux_session) : '') || member.session_uuid.slice(0, 8);
}


export const TOGGLE_WIDTH = 40;

export function toggleWidthFor(sessionId: string): number {
  if (!layoutActive() || layoutMode.naming) return 0;
  return memberForRow(rowIdForSession(sessionId)) ? TOGGLE_WIDTH : 0;
}
