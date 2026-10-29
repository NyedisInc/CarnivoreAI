import type { SessionInfo } from '../../api';
import { browserMenuContext } from '../../../lib/sidebar-shell/row-plan';
import { contextFromRow, type RowMenuCtx } from '../../../lib/item-menu/row-context';
import type { ItemMenuOpenOptions } from '../../../lib/item-menu/open.svelte';
import { isAsleepRow } from '../running-sessions/asleep';

interface RowMenuGlobals {
  CloudeWeb?: {
    rowMenu?: {
      openRow(ctx: RowMenuCtx, anchor: Element, at: { x: number; y: number } | null, opts: ItemMenuOpenOptions): boolean;
      isOpen(): boolean;
      closeRow(): void;
    };
  };
  SessionSidebarGroupActions?: object;
  SessionSidebarGroupMembership?: { uuidOfName(tmuxName: string): string | null };
}


export interface RowMenuOptions {
  point?: { x: number; y: number };
  host?: HTMLElement;
  onClose?: () => void;
}

function menuRow(row: SessionInfo, uuid: string | null): Record<string, unknown> {
  const wire = row as unknown as Record<string, unknown>;
  const asleep = isAsleepRow(row);
  return {
    name: row.tmux_session ?? '',
    label: row.label,
    session_id: asleep ? null : row.session?.id ?? null,
    session_uuid: uuid ?? '',
    ...(asleep ? { asleep: true, agent_family: row.agent_family ?? null } : {}),
    status: asleep ? 'asleep' : row.activity_status || 'unknown',
    unread: !!row.unread,
    created_by_cloude: typeof wire.created_by_us === 'boolean' ? wire.created_by_us : !!wire.created_by_cloude,
    project_id: row.project_id ?? null,
    host_key: row.host_key ?? 'local',
    agent_update: wire.agent_update ?? null,
    mcp_health: wire.mcp_health ?? null,
    subagents_running: row.subagents_running ?? null,
    background_open: row.background_open ?? null,
    timers_live: row.timers_live ?? null,
    notifications_muted: !!wire.notifications_muted,
  };
}

export function uuidOfTmuxName(tmuxName: string | null | undefined): string | null {
  if (!tmuxName) return null;
  return (globalThis as unknown as RowMenuGlobals).SessionSidebarGroupMembership?.uuidOfName(tmuxName) ?? null;
}

const bridge = (): NonNullable<NonNullable<RowMenuGlobals['CloudeWeb']>['rowMenu']> | undefined =>
  (globalThis as unknown as RowMenuGlobals).CloudeWeb?.rowMenu;

export function closeRowMenu(): void {
  bridge()?.closeRow();
}

export function openRowMenu(row: SessionInfo, uuid: string | null, anchor: HTMLElement, options: RowMenuOptions = {}): boolean {
  if (!row.tmux_session) return false;
  const ctx = contextFromRow(menuRow(row, uuid), {
    surface: 'sidebar', renameable: isAsleepRow(row) ? !!uuid : !!row.session?.id, band: '',
  });
  const pinnedTheme = options.host ? undefined : row.pinned_theme ?? null;
  return openContextMenu(ctx, anchor, options, pinnedTheme);
}

export type BrowserItemKind = 'browser' | 'page' | 'file';

export function openBrowserItemMenu(
  kind: BrowserItemKind, id: string, label: string, anchor: HTMLElement, options: RowMenuOptions = {},
): boolean {
  const g = globalThis as unknown as RowMenuGlobals;
  const ctx = browserMenuContext(
    { name: `browser:${id}`, label, page: kind === 'page', file: kind === 'file' },
    !!g.SessionSidebarGroupActions,
  ) as unknown as RowMenuCtx;
  return openContextMenu(ctx, anchor, options, null);
}

function openContextMenu(ctx: RowMenuCtx, anchor: HTMLElement, options: RowMenuOptions, pinnedTheme: string | null | undefined): boolean {
  const menu = bridge();
  if (!menu) return false;
  return menu.openRow(ctx, anchor, options.point ?? null, { nestedIn: options.host ?? null, onClose: options.onClose, pinnedTheme });
}
