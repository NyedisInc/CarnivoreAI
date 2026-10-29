import type { UsageLimit } from '../../opscenter/api/types';
import { addRows } from './asleep';
import { addClosedRows } from './closed';
import { closedShown } from './closed-visibility.svelte';
import { sectionShown } from './section-visibility.svelte';
import { searchLists } from './search';
import { filterAwakeSleeping } from './bucketing';
import { archivedRows } from './archived-rows';
import * as Archived from './archived-visibility';
import { fromError, type ListingVerdict } from './listing-state';
import * as Identity from './row-identity';
import * as GroupStore from './group-store';
import { liveRuleContext } from './group-rule-live';
import { reconcile } from './store-rebind';
import { noteRows } from './sync';
import { drawerEnv } from './env';
import { rows as browserRows } from './browser-rows';
import { refreshGroups } from '../sidebar-shell/interaction-globals';
import { openFiles } from '../open-files/api.svelte';
import { isDirty } from '../open-files/buffers.svelte';
import { fileDrawerRows } from '../open-files/rows';
import { rowLooks, stampLooks } from '../open-files/row-looks';

export type DrawerRow = Record<string, unknown> & { name: string };

export interface LiveInfo {
    tmux_session?: string;
    session?: { id?: string; working_dir?: string | null } | null;
    activity_status?: string;
    unread?: boolean;
    created_by_us?: boolean;
    created_by_cloude?: boolean;
    host_key?: string;
    host_label?: string;
    host_state?: string;
    parked_summary?: string | null;
    usage_limit?: UsageLimit | null;
    background_open?: number | null;
    agent_update?: { running: string; installed: string; ready: boolean } | null;
    mcp_health?: {
        servers?: { name: string; transport: string; state: string; reason: string; source: string;
                    detail?: string | null; at?: string | null; exact?: boolean }[];
        dropped: { name: string; state: string; at?: string | null; exact?: boolean; source?: string }[];
    } | null;
    account_id?: string | null;
    automation?: { automation_id: string; run_id: string; name: string } | null;
    automations_state?: string | null;
    automations_total?: number | null;
    automations_enabled?: number | null;
    automations_next?: unknown;
    messaging?: { directions: string[]; held: number } | null;
    notifications_muted?: boolean;
    task_lead?: boolean | null;
    do_not_disturb?: boolean | null;
    claude_session_uuid?: string | null;
    [field: string]: unknown;
}

interface FetchGlobals {
    API?: {
        listAttachableSessions(): Promise<unknown>;
        listSessions?(): Promise<unknown>;
        listSessionCompanions?(): Promise<unknown>;
        listSessionRecords?(): Promise<unknown>;
    };
    UIFlags?: { ensure?(): unknown };
    SessionHeaderLed?: {
        beginRequest?(): unknown;
        update?(rows: unknown[], active: string | null, request?: unknown): void;
    };
    SessionSidebarLayouts?: { rows(rows: DrawerRow[]): DrawerRow[]; memberUuids?(): Set<string> };
    CloudeWeb?: { layoutPage?: { isActive?(): boolean } };
}

function g(): FetchGlobals {
    return drawerEnv() as FetchGlobals;
}

export function statusOf(err: unknown): number {
    const s = (err as { status?: unknown } | null)?.status;
    return typeof s === 'number' ? s : 0;
}

let loadGeneration = 0;

export function inLayoutPage(): boolean {
    const page = g().CloudeWeb?.layoutPage;
    return !!(page && typeof page.isActive === 'function' && page.isActive());
}

export async function load(activeTmuxName: string | null): Promise<{ rows: DrawerRow[]; listing: ListingVerdict }> {
    const generation = ++loadGeneration;
    const G = g();
    const headerRequest = G.SessionHeaderLed?.beginRequest?.();
    let rows: DrawerRow[] = [];
    let listing: ListingVerdict = { ok: true, reason: null, detail: null };

    if (G.UIFlags && typeof G.UIFlags.ensure === 'function') G.UIFlags.ensure();

    const api = G.API;
    try {
        const attachable = await api!.listAttachableSessions();
        rows = Array.isArray(attachable) ? (attachable as DrawerRow[]).slice() : [];
    } catch (err) {
        console.error('SessionSidebar: listAttachableSessions failed:', err);
        listing = fromError(err, statusOf(err));
        rows = [];
    }

    try {
        const live = api && typeof api.listSessions === 'function' ? await api.listSessions() : [];
        for (const info of Array.isArray(live) ? live as LiveInfo[] : []) mergeLiveRow(rows, info);
        if (!listing.ok && rows.length > 0) {
            listing = {
                ok: false,
                reason: listing.reason,
                detail: `${listing.detail}; only sessions with a live backend are listed`,
            };
        }
    } catch (err) {
        console.warn('SessionSidebar: listSessions unavailable:', (err as Error)?.message);
    }

    try {
        const companions = api && typeof api.listSessionCompanions === 'function' ? await api.listSessionCompanions() : [];
        for (const info of Array.isArray(companions) ? companions as LiveInfo[] : []) mergeLiveRow(rows, info);
    } catch (err) {
        console.warn('SessionSidebar: companion shells unavailable:', (err as Error)?.message);
    }

    let workByName = new Map<string, string>();
    let records: unknown[] = [];
    try {
        if (api && typeof api.listSessionRecords === 'function') {
            const got = await api.listSessionRecords();
            records = Array.isArray(got) ? got : [];
            workByName = workStampIndex(records);
        }
    } catch (err) {
        console.warn('SessionSidebar: session records unavailable:', (err as Error)?.message);
    }
    addRows(rows, records, G.SessionSidebarLayouts?.memberUuids?.());
    if (closedShown()) addClosedRows(rows, records);
    noteIdentities(rows, records as Identity.SessionRecord[]);

    const inLayout = inLayoutPage();
    for (const row of rows) {
        row.is_this_tab = !inLayout && !!activeTmuxName && row.name === activeTmuxName;
        row.last_work_at = workByName.get(row.name) || null;
        row.project_id = row.project_id !== undefined ? row.project_id : null;
        row.project_name = row.project_name !== undefined ? row.project_name : null;
        row.working_dir = row.working_dir !== undefined ? row.working_dir : null;
        row.running_model = row.running_model !== undefined ? row.running_model : null;
        row.running_model_effort = row.running_model_effort !== undefined ? row.running_model_effort : null;
        row.running_model_tier = row.running_model_tier !== undefined ? row.running_model_tier : null;
        row.running_context_used_pct = row.running_context_used_pct !== undefined ? row.running_context_used_pct : null;
    }
    if (!searchLists()) rows = filterAwakeSleeping(rows, sectionShown('open'), sectionShown('sleeping'));
    if (Archived.archivedShown()) {
        await Archived.freshen();
        rows.push(...archivedRows(Archived.archivedRecords(), Archived.archivedShown(), new Set(rows.map((r) => r.name))));
    }
    rows.push(...(browserRows() as unknown as DrawerRow[]));
    rows.push(...fileDrawerRows(openFiles.data ?? [], isDirty));
    stampLooks(rows, rowLooks.data);
    if (G.SessionSidebarLayouts) rows.push(...G.SessionSidebarLayouts.rows(rows));
    const sorted = defaultSort(rows);
    if (G.SessionHeaderLed && typeof G.SessionHeaderLed.update === 'function' && generation === loadGeneration) {
        G.SessionHeaderLed.update(sorted, activeTmuxName, headerRequest);
    }
    return { rows: sorted, listing };
}

export function noteIdentities(rows: DrawerRow[], records: readonly Identity.SessionRecord[]): void {
    Identity.stamp(rows, records);
    reconcile(rows as Array<{ name: string; session_uuid?: string | null }>);
    noteRows(rows as Array<{ name: string; session_uuid?: string | null }>);
    GroupStore.setRuleContext(liveRuleContext);
    GroupStore.setIdentities(rows as Array<{ name: string; session_uuid?: string | null }>);
    if (Identity.namesChanged(rows)) void refreshGroups();
}

function createdByUs(info: LiveInfo): boolean {
    if (typeof info.created_by_us === 'boolean') return info.created_by_us;
    return !!info.created_by_cloude;
}

function orNull(v: unknown): unknown {
    return v !== undefined ? v : null;
}

function liveFields(info: LiveInfo): Partial<DrawerRow> {
    return {
        is_active: true,
        session_id: (info.session && info.session.id) || null,
        working_dir: (info.session && info.session.working_dir) || null,
        status: info.activity_status || 'unknown',
        unread: !!info.unread,
        created_by_cloude: createdByUs(info),
        startup_gate: info.startup_gate,
        status_source: info.status_source,
        activity_hint: orNull(info.activity_hint),
        parked_summary: orNull(info.parked_summary),
        usage_limit: orNull(info.usage_limit),
        project_id: orNull(info.project_id),
        project_name: orNull(info.project_name),
        claude_session_uuid: orNull(info.claude_session_uuid),
        running_model: orNull(info.running_model),
        running_model_effort: orNull(info.running_model_effort),
        running_model_tier: orNull(info.running_model_tier),
        running_context_used_pct: orNull(info.running_context_used_pct),
        spectator_expires_at: orNull(info.spectator_expires_at),
        subagents_running: orNull(info.subagents_running),
        subagents_total: orNull(info.subagents_total),
        workflow_active: orNull(info.workflow_active),
        timers_live: orNull(info.timers_live),
        timers_next_fire_at: orNull(info.timers_next_fire_at),
        automations_state: orNull(info.automations_state),
        automations_total: orNull(info.automations_total),
        automations_enabled: orNull(info.automations_enabled),
        automations_next: orNull(info.automations_next),
        background_open: orNull(info.background_open),
        agent_update: orNull(info.agent_update),
        mcp_health: orNull(info.mcp_health),
        account_id: orNull(info.account_id),
        automation: orNull(info.automation),
        messaging: orNull(info.messaging),
        notifications_muted: !!info.notifications_muted,
        task_lead: orNull(info.task_lead),
        do_not_disturb: orNull(info.do_not_disturb),
        host_key: info.host_key ?? 'local',
        host_label: info.host_label ?? 'this machine',
        host_state: info.host_state ?? 'up',
    };
}

export function mergeLiveRow(rows: DrawerRow[], info: LiveInfo): void {
    const tmuxName = info && info.tmux_session;
    if (!tmuxName) return;
    const rowId = typeof info.session_row_id === 'number' ? info.session_row_id : null;
    const existing = rows.find((r) => r.name === tmuxName);
    if (existing) {
        Object.assign(existing, liveFields(info));
        if (rowId !== null) existing.session_row_id = rowId;
        if (info.label !== undefined) existing.label = info.label;
        if (info.agent_family !== undefined) existing.agent_family = info.agent_family;
        if (info.agent_family_source !== undefined) existing.agent_family_source = info.agent_family_source;
        if (info.agent_wrapper_icon !== undefined) existing.agent_wrapper_icon = info.agent_wrapper_icon;
        if (info.pinned_theme) existing.pinned_theme = info.pinned_theme;
        return;
    }
    rows.unshift({
        name: tmuxName,
        label: orNull(info.label),
        created_at_epoch: 0,
        session_row_id: rowId,
        agent_family: orNull(info.agent_family),
        agent_family_source: orNull(info.agent_family_source),
        agent_wrapper_icon: orNull(info.agent_wrapper_icon),
        pinned_theme: info.pinned_theme || null,
        ...liveFields(info),
    } as DrawerRow);
}

export function workStampIndex(records: readonly unknown[]): Map<string, string> {
    const index = new Map<string, string>();
    for (const raw of Array.isArray(records) ? records : []) {
        const row = raw as { tmux_name?: string; last_work_at?: string } | null;
        if (!row || !row.tmux_name || !row.last_work_at) continue;
        const seen = index.get(row.tmux_name);
        if (!seen || row.last_work_at > seen) index.set(row.tmux_name, row.last_work_at);
    }
    return index;
}

export function defaultSort(rows: DrawerRow[]): DrawerRow[] {
    return rows.sort((a, b) => {
        const aw = a && a.last_work_at as string | null;
        const bw = b && b.last_work_at as string | null;
        if (!!aw !== !!bw) return aw ? -1 : 1;
        if (aw && bw && aw !== bw) return aw < bw ? 1 : -1;
        return ((b.created_at_epoch as number) || 0) - ((a.created_at_epoch as number) || 0);
    });
}

export function workAttr(row: Record<string, unknown> | null | undefined): string {
    if (row && row.last_work_at) {
        const safe = String(row.last_work_at).replace(/[^0-9TZ:.+-]/g, '');
        return `data-work="recorded" data-work-at="${safe}" `;
    }
    return 'data-work="unrecorded" ';
}
