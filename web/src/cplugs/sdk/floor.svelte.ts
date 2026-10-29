import { companies } from '../../lib/companies';
import { floorFeedRows } from '../../lib/drawer/floor-feed.svelte';
import { isAgentKind, type BucketRow } from '../../lib/drawer/bucketing';
import { rowHost } from '../../lib/sidebar-shell/row-host';
import { hostDocument, hostWindow } from '../../lib/sessions/env';
import { projects } from '../../opscenter/api/projects.svelte';
import { openSession, sessionRow, type ListingRow } from './sessions.svelte';

export interface FloorSession {
  key: string;
  name: string;
  label: string;
  sessionId: string | null;
  sessionUuid: string | null;
  sessionRowId: number | null;
  asleep: boolean;
  projectId: number | null;
  projectName: string | null;
  harness: string | null;
  remote?: boolean;
  listing: ListingRow;
}

export interface FloorCompany {
  id: number;
  name: string;
  hue?: number | null;
}

export interface FloorProject {
  id: number;
  name: string;
  companyId: number | null;
}

export interface FloorSource {
  sessions: FloorSession[];
  companies: FloorCompany[];
  projects: FloorProject[];
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null;
}

function listingOf(r: Readonly<Record<string, unknown>>, sessionId: string | null): ListingRow {
  const pushed = sessionId ? sessionRow(sessionId) : undefined;
  if (pushed) return pushed;
  const pct = r.running_context_used_pct;
  return {
    activity_status: text(r.status),
    startup_gate: text(r.startup_gate),
    running_context_used_pct: typeof pct === 'number' ? pct : null,
    tmux_session: text(r.name),
  };
}

function sessionOf(r: Readonly<Record<string, unknown>> & { name: string }): FloorSession {
  const uuid = text(r.session_uuid);
  const asleep = r.asleep === true;
  const sessionId = asleep ? null : text(r.session_id);
  const local = !text(r.host_key) || r.host_key === 'local';
  const rowId = !local ? null : typeof r.session_row_id === 'number' ? r.session_row_id : typeof r.id === 'number' ? r.id : null;
  const label = rowHost().label?.resolve(r as never) || text(r.label) || r.name;
  return {
    key: uuid ?? `${text(r.host_key) ?? 'local'}:${r.name}`,
    name: r.name,
    label,
    sessionId,
    sessionUuid: uuid,
    sessionRowId: rowId,
    asleep,
    projectId: typeof r.project_id === 'number' ? r.project_id : null,
    projectName: text(r.project_name),
    harness: text(r.agent_family),
    remote: !local,
    listing: listingOf(r, sessionId),
  };
}

export function floorSource(): FloorSource {
  return {
    sessions: floorFeedRows().filter((r) => isAgentKind(r as BucketRow)).map(sessionOf),
    companies: companies.list.map((c) => ({ id: c.id, name: c.name, hue: c.hue ?? null })),
    projects: (projects.data ?? []).flatMap((p): FloorProject[] =>
      p.id !== null && p.id !== undefined && !p.archived_at ? [{ id: p.id, name: p.name, companyId: p.company_id ?? null }] : []),
  };
}

/* nothing opened */
export async function openFloorSession(session: FloorSession): Promise<boolean> {
  if (!session.asleep && session.sessionId) return openSession(session.sessionId, session.name);
  const g = hostWindow() as unknown as { SessionSidebar?: unknown; SessionSidebarClicks?: { activateRow(ctrl: unknown, row: Element): Promise<void> }; SessionSidebarWakeClick?: { onAsleepClick(ctrl: unknown, row: Element, open: unknown): Promise<boolean> } } | undefined;
  const name = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(session.name) : session.name;
  const row = hostDocument()?.querySelector?.(`.session-sidebar-row[data-name="${name}"]`) ?? null;
  if (!row || !g?.SessionSidebar || !g.SessionSidebarClicks) return false;
  const clicks = g.SessionSidebarClicks;
  if (session.asleep && g.SessionSidebarWakeClick) await g.SessionSidebarWakeClick.onAsleepClick(g.SessionSidebar, row, clicks.activateRow);
  else await clicks.activateRow(g.SessionSidebar, row);
  return false;
}
