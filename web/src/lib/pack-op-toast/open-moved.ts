/* conversation id */
import type { PackOp } from './op-text';

interface Row {
  host_label?: string | null;
  claude_session_uuid?: string | null;
  session?: { id?: string; claude_session_uuid?: string | null };
}

export function movedSessionId(op: PackOp, rows: Row[] | null): string | null {
  if (op.kind !== 'session' || op.direction !== 'out' || op.running || op.state !== 'moved' || !op.claude_session_uuid || op.mode === 'fresh') return null;
  const found = (rows ?? []).find((r) => r.host_label === op.machine && (r.claude_session_uuid ?? r.session?.claude_session_uuid) === op.claude_session_uuid);
  return found?.session?.id ?? null;
}

function listingRows(): Row[] | null {
  const found = (globalThis as { ListingPush?: { rows?(name: string): Row[] | null } }).ListingPush;
  return found && typeof found.rows === 'function' ? found.rows('list') : null;
}

export function openableId(op: PackOp): string | null {
  return movedSessionId(op, listingRows());
}

export async function openMoved(op: PackOp): Promise<boolean> {
  const id = openableId(op);
  const nav = (globalThis as { ToastNavigate?: { go(toast: { session_id: string }): Promise<boolean> } }).ToastNavigate;
  if (!id || !nav) return false;
  return nav.go({ session_id: id });
}
