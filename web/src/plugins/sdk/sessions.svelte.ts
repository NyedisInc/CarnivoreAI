import { whenListingPushBooted } from '../../lib/listing-push/boot';
import { browserSessionsSearchHost } from '../../lib/sessions-search/host';
import { hostWindow } from '../../lib/sessions/env';
import { addSession, refusalLine } from '../../opscenter/engine/components-actions';
import type { LayoutStore } from '../../opscenter/engine/layout.svelte';
import type { SessionInfo } from '../../opscenter/api/types';
import { openWarroomModal } from '../../lib/warroom/modal';

export interface ListingRow {
  activity_status?: string | null;
  label?: string | null;
  unread?: boolean;
  status_source?: string | null;
  activity_hint?: string | null;
  claude_session_uuid?: string | null;
  startup_gate?: string | null;
  running_context_used_pct?: number | null;
  tmux_session?: string | null;
  host_key?: string | null;
  host_label?: string | null;
  host_state?: string | null;
  prompt_suggestion?: string | null;
  session?: { id?: string };
}

interface ListingSource {
  rows?(name: string): ListingRow[] | null;
  onChange?(fn: (names: string[]) => void): () => void;
}

const listing = $state<{ version: number }>({ version: 0 });
let index = new Map<string, ListingRow>();
let subscribed = false;

function reindex(bump = true): void {
  const push = (globalThis as { ListingPush?: ListingSource }).ListingPush;
  const rows = push && typeof push.rows === 'function' ? push.rows('list') : null;
  index = new Map((rows ?? []).flatMap((row): Array<[string, ListingRow]> => (row?.session?.id ? [[row.session.id, row]] : [])));
  if (bump) listing.version += 1;
}

function follow(): void {
  if (subscribed) return;
  subscribed = true;
  let inline = true;
  whenListingPushBooted(() => {
    const push = (globalThis as { ListingPush?: ListingSource }).ListingPush;
    reindex(!inline);
    push?.onChange?.((names) => {
      if (names.includes('list') || names.includes('$live')) reindex();
    });
  });
  inline = false;
}

export function sessionRow(sessionId: string | null): ListingRow | undefined {
  follow();
  void listing.version;
  return sessionId ? index.get(sessionId) : undefined;
}

export function sessionRowForConversation(conversationId: string): ListingRow | undefined {
  follow();
  void listing.version;
  for (const row of index.values()) if (row.claude_session_uuid === conversationId) return row;
  return undefined;
}

export function openSession(sessionId: string, tmuxName: string): Promise<boolean> {
  return browserSessionsSearchHost().navigate(sessionId, tmuxName);
}

export function terminalAvailable(): boolean {
  const app = (hostWindow() as unknown as { App?: { returnToExistingTerminal?: unknown } } | undefined)?.App;
  return typeof app?.returnToExistingTerminal === 'function';
}

export function openSessionModal(sessionId: string | null): boolean {
  const row = sessionRow(sessionId);
  if (!row || !terminalAvailable()) return false;
  openWarroomModal(row as unknown as SessionInfo);
  return true;
}

export function addTerminalCell(store: LayoutStore, sessionId: string): string {
  return refusalLine(addSession(store, 'terminal', sessionId), 'terminal');
}
