import { pluginItemsFor } from './row-plugins';
import { swarmRosterAgents } from '../../cplugs/sdk/swarm-roster.svelte';
import { memberOf } from '../swarm-membership/member-face';
import { escHtml } from '../drawer/row-controls';

export interface RowMenuCtx {
    name: string;
    label: string;
    sessionId: string | null;
    sessionUuid: string;
    conversationId: string;
    asleep: boolean;
    archived: boolean;
    closed: boolean;
    projectId: number | null;
    surface: string;
    kind?: string;
    layoutUuid?: string;
    owned: boolean;
    status: string;
    unread: boolean;
    restartable: boolean;
    hostKey: string;
    agentFamily: string;
    pluginItems: string;
    groupable: boolean;
    groupUuid: string;
    groupName: string;
    renameable: boolean;
    renameReason: string;
    isPage?: boolean;
    isFile?: boolean;
    forkable: boolean;
    forkReason: string;
    muted: boolean;
    mcpDropped: boolean;
    mcpTooltip?: string;
    mcpServers: string;
    agentUpdateReady: boolean;
    agentUpdateRunning: string;
    agentUpdateInstalled: string;
    updateBusy: boolean;
    updateBusyReason: string;
    menuHidden?: boolean;
    swarmRank?: string;
    shiftHeld?: boolean;
}

export interface RowTriggerSpec {
    attrs: Record<string, string | undefined>;
    svg: string;
}

export const TRIGGER_ATTR = 'data-row-menu';
export const TRIGGER_CLASS = 'session-row-menu-trigger';
export const TRIGGER_UPDATE_CLASS = 'session-row-menu-trigger--update';
export const TRIGGER_MCP_CLASS = 'session-row-menu-trigger--mcp';
export const TRIGGER_DIM_CLASS = 'session-row-menu-trigger--dim';
export const ROW_MENU_PANEL_ID = 'session-row-menu-panel';
export const FORK_REASON = 'cannot fork: carnivore did not create this agent, so it has no recorded conversation to branch from';

interface RowContextGlobals {
    CloudeI18n?: { t(key: string, vars?: Record<string, unknown>): string };
    SessionRowActions?: { actionsFor(status: string, o: { owned: boolean }): string[]; ACTION_RESTART?: string };
    SessionSidebarGroupStore?: { groupUuidOf?(band: string): string | null; groupByUuid?(uuid: string): { name?: string } | null };
    SessionRowMenuIcons?: { svg(id: string, size?: number): string };
    KebabIcon?: { svg(size: number, stroke: number): string };
}

const g = (): RowContextGlobals => globalThis as unknown as RowContextGlobals;

export interface RowContextOptions {
    surface?: string;
    renameable?: boolean;
    renameReason?: string;
    band?: string;
    menuHidden?: boolean;
}

const muteOverride = new Map<string, boolean>();

export function mutedFor(name: string, payload: unknown): boolean {
    if (name && muteOverride.has(name)) return !!muteOverride.get(name);
    return payload === true;
}

export function setMuteOverride(name: string, muted: boolean | null): void {
    if (!name) return;
    if (muted === null) muteOverride.delete(name);
    else muteOverride.set(name, !!muted);
}

function tr(key: string, vars?: Record<string, unknown>): string {
    const i18n = g().CloudeI18n;
    return i18n && typeof i18n.t === 'function' ? i18n.t(key, vars) : '';
}

interface McpServer { name: string; state?: string; reason?: string; detail?: string }
interface McpDrop { name?: string; source?: string }

export function mcpAlerts(row: Record<string, unknown>): { names: string; firstHand: boolean; text: string } {
    const health = (row.mcp_health ?? null) as { servers?: McpServer[]; dropped?: McpDrop[] } | null;
    const servers = health && Array.isArray(health.servers) ? health.servers : [];
    if (!servers.length) {
        const drops = health && Array.isArray(health.dropped) ? health.dropped : [];
        const legacy = drops.map((d) => d && d.name).filter(Boolean).join(', ');
        const firstHand = drops.some((d) => d && d.source === 'server');
        return {
            names: legacy, firstHand,
            text: legacy ? (tr(firstHand ? 'mcp.dropped_first_hand' : 'mcp.dropped_tooltip', { servers: legacy }) || legacy) : '',
        };
    }
    const down = servers.filter((s) => s && (s.state === 'down' || s.state === 'needs_auth'));
    const names = down.map((s) => s.name).join(', ');
    const parts = down.map((s) => {
        let reason = tr(`mcp.reason.${s.reason}`) || s.reason || '';
        if (s.detail) reason = tr('mcp.reason_detail', { reason, detail: s.detail }) || reason;
        return tr('mcp.server_reason', { name: s.name, reason }) || s.name;
    });
    return { names, firstHand: false, text: names ? (tr('mcp.down_tooltip', { servers: parts.join('; ') }) || names) : '' };
}

function busyBits(row: Record<string, unknown>): string[] {
    const out: string[] = [];
    const count = (field: string, one: string, many: string, verb: string): void => {
        const n = row[field];
        if (typeof n === 'number' && n > 0) out.push(`${n} ${n === 1 ? one : many} ${verb}`);
    };
    count('subagents_running', 'subagent', 'subagents', 'running');
    count('background_open', 'shell', 'shells', 'open');
    count('timers_live', 'timer', 'timers', 'live');
    return out;
}

export function contextFromRow(r: Record<string, unknown> | null | undefined, opts: RowContextOptions = {}): RowMenuCtx {
    const row = r ?? {};
    const G = g();
    const owned = !!row.created_by_cloude;
    const name = typeof row.name === 'string' ? row.name : '';
    const forkable = owned && !!name;
    const status = (row.status as string) || 'unknown';
    const acts = G.SessionRowActions;
    const actions = acts && typeof acts.actionsFor === 'function' ? acts.actionsFor(status, { owned }) : [];
    const restartable = actions.includes(acts?.ACTION_RESTART ?? 'restart');
    const asleep = !!row.asleep;
    const pluginItems = asleep || row.archived === true ? '' : pluginItemsFor(row).map((i) => i.id).join(',');
    const surface = opts.surface || 'sidebar';
    const groupable = surface === 'sidebar';
    const store = G.SessionSidebarGroupStore;
    let groupUuid = groupable && store && typeof store.groupUuidOf === 'function' ? store.groupUuidOf(opts.band || '') : null;
    const groupRecord = groupUuid && store && typeof store.groupByUuid === 'function' ? store.groupByUuid(groupUuid) : null;
    if (groupUuid && !groupRecord) groupUuid = null;
    const update = (row.agent_update ?? null) as { ready?: boolean; running?: unknown; installed?: unknown } | null;
    const updateReady = !!(update && update.ready === true && typeof update.running === 'string' && typeof update.installed === 'string');
    const mcp = mcpAlerts(row);
    const busy = busyBits(row);
    return {
        name,
        label: (row.label != null && String(row.label)) || '',
        sessionId: (row.session_id as string) || null,
        sessionUuid: (row.session_uuid as string) || '',
        conversationId: (row.claude_session_uuid as string) || '',
        asleep,
        archived: row.archived === true,
        closed: row.closed === true,
        projectId: row.project_id !== undefined ? (row.project_id as number | null) : null,
        surface,
        owned,
        status,
        unread: !!row.unread,
        restartable: restartable && row.closed !== true && row.archived !== true,
        hostKey: (row.host_key as string) || 'local',
        agentFamily: (row.agent_family as string) || '',
        pluginItems,
        groupable,
        groupUuid: groupUuid || '',
        groupName: groupRecord?.name || '',
        renameable: !!opts.renameable,
        renameReason: opts.renameReason || '',
        forkable,
        forkReason: forkable ? '' : FORK_REASON,
        muted: mutedFor(name, row.notifications_muted),
        mcpDropped: mcp.names !== '',
        mcpTooltip: mcp.text,
        mcpServers: mcp.names,
        agentUpdateReady: updateReady,
        agentUpdateRunning: updateReady ? (update!.running as string) : '',
        agentUpdateInstalled: updateReady ? (update!.installed as string) : '',
        updateBusy: busy.length > 0,
        updateBusyReason: busy.length > 0 ? `cannot update and restart: ${busy.join(', ')} - a restart would end it` : '',
        menuHidden: !!opts.menuHidden,
        swarmRank: memberOf(row, swarmRosterAgents())?.rank ?? '',
    };
}

const str = (value: unknown): string => (value == null ? '' : String(value));

export function updateTitle(running: string, installed: string, shiftHeld: boolean): string {
    return shiftHeld ? 'click: update and restart now' : `update ready: ${running} → ${installed}, shift-click to restart now`;
}

export function triggerSpec(c: Partial<RowMenuCtx>): RowTriggerSpec {
    const shown = c.label || c.name;
    let title = c.agentUpdateReady ? updateTitle(str(c.agentUpdateRunning), str(c.agentUpdateInstalled), false) : '';
    const mcpShown = !!c.mcpDropped && !c.agentUpdateReady;
    if (mcpShown) title = c.mcpTooltip || c.mcpServers || '';
    const dimmed = !!c.menuHidden && !c.agentUpdateReady && !mcpShown;
    const attrs: Record<string, string | undefined> = {
        type: 'button',
        class: TRIGGER_CLASS + (c.agentUpdateReady ? ` ${TRIGGER_UPDATE_CLASS}` : '') + (mcpShown ? ` ${TRIGGER_MCP_CLASS}` : '')
            + (dimmed ? ` ${TRIGGER_DIM_CLASS}` : ''),
        'data-menu-hidden': dimmed ? '1' : undefined,
        [TRIGGER_ATTR]: str(c.name),
        'data-row-menu-label': str(c.label),
        'data-row-menu-session-id': str(c.sessionId || ''),
        'data-row-menu-session-uuid': str(c.sessionUuid || ''),
        'data-row-menu-conversation-id': c.conversationId ? str(c.conversationId) : undefined,
        'data-row-menu-asleep': c.asleep ? '1' : '0',
        'data-row-menu-archived': c.archived ? '1' : undefined,
        'data-row-menu-closed': c.closed ? '1' : undefined,
        'data-row-menu-project-id': c.projectId != null ? String(c.projectId) : '',
        'data-row-menu-surface': str(c.surface),
        'data-row-menu-kind': str(c.kind || 'session'),
        'data-row-menu-layout-uuid': str(c.layoutUuid || ''),
        'data-row-menu-owned': c.owned ? '1' : '0',
        'data-row-menu-status': str(c.status),
        'data-row-menu-unread': c.unread ? '1' : '0',
        'data-row-menu-restartable': c.restartable ? '1' : '0',
        'data-row-menu-host-key': str(c.hostKey || 'local'),
        'data-row-menu-agent-family': str(c.agentFamily || ''),
        'data-row-menu-plugin-items': str(c.pluginItems || ''),
        'data-row-menu-groupable': c.groupable ? '1' : '0',
        'data-row-menu-group-uuid': str(c.groupUuid || ''),
        'data-row-menu-group-name': str(c.groupName || ''),
        'data-row-menu-renameable': c.renameable ? '1' : '0',
        'data-row-menu-rename-reason': str(c.renameReason),
        'data-row-menu-page': c.isPage ? '1' : undefined,
        'data-row-menu-file': c.isFile ? '1' : undefined,
        'data-row-menu-forkable': c.forkable ? '1' : '0',
        'data-row-menu-fork-reason': str(c.forkReason),
        'data-row-menu-muted': c.muted ? '1' : '0',
        'data-row-menu-mcp-dropped': c.mcpDropped ? '1' : undefined,
        'data-row-menu-mcp-servers': c.mcpDropped ? str(c.mcpServers || '') : undefined,
        'data-row-menu-update-ready': c.agentUpdateReady ? '1' : '0',
        'data-row-menu-update-running': str(c.agentUpdateRunning || ''),
        'data-row-menu-update-installed': str(c.agentUpdateInstalled || ''),
        'data-row-menu-update-busy': c.updateBusy ? '1' : '0',
        'data-row-menu-update-busy-reason': str(c.updateBusyReason || ''),
        'data-row-menu-swarm-rank': c.swarmRank ? str(c.swarmRank) : undefined,
        'data-tooltip': str(title),
        tabindex: '-1',
        'aria-haspopup': 'menu',
        'aria-expanded': 'false',
        'aria-controls': ROW_MENU_PANEL_ID,
        'aria-label': str(c.agentUpdateReady || mcpShown ? title : `agent actions for ${shown}`),
    };
    const icons = g().SessionRowMenuIcons;
    const kebab = g().KebabIcon;
    const svg = c.agentUpdateReady
        ? (icons ? icons.svg('update-restart', 14) : '')
        : mcpShown ? (icons ? icons.svg('mcp-drop', 14) : '') : (kebab ? kebab.svg(14, 1.4) : '');
    return { attrs, svg };
}

function esc(value: string): string {
    return escHtml(value);
}

export function triggerHtml(c: Partial<RowMenuCtx>): string {
    const spec = triggerSpec(c);
    const parts = Object.keys(spec.attrs).filter((k) => spec.attrs[k] !== undefined).map((k) => `${k}="${esc(spec.attrs[k] as string)}"`);
    return `<button ${parts.join(' ')}>${spec.svg}</button>`;
}

export function contextFromTrigger(el: Element | null | undefined): RowMenuCtx | null {
    if (!el || typeof el.getAttribute !== 'function') return null;
    const attr = (n: string): string => el.getAttribute(n) || '';
    const flag = (n: string): boolean => attr(n) === '1';
    return {
        name: attr(TRIGGER_ATTR),
        label: attr('data-row-menu-label'),
        sessionId: attr('data-row-menu-session-id') || null,
        sessionUuid: attr('data-row-menu-session-uuid'),
        conversationId: attr('data-row-menu-conversation-id'),
        asleep: flag('data-row-menu-asleep'),
        archived: flag('data-row-menu-archived'),
        closed: flag('data-row-menu-closed'),
        projectId: attr('data-row-menu-project-id') !== '' ? Number(attr('data-row-menu-project-id')) : null,
        surface: attr('data-row-menu-surface') || 'sidebar',
        kind: attr('data-row-menu-kind') || 'session',
        layoutUuid: attr('data-row-menu-layout-uuid') || '',
        owned: flag('data-row-menu-owned'),
        status: attr('data-row-menu-status') || 'unknown',
        unread: flag('data-row-menu-unread'),
        restartable: flag('data-row-menu-restartable'),
        hostKey: attr('data-row-menu-host-key') || 'local',
        agentFamily: attr('data-row-menu-agent-family'),
        pluginItems: attr('data-row-menu-plugin-items'),
        groupable: flag('data-row-menu-groupable'),
        groupUuid: attr('data-row-menu-group-uuid'),
        groupName: attr('data-row-menu-group-name'),
        renameable: flag('data-row-menu-renameable'),
        renameReason: attr('data-row-menu-rename-reason'),
        isPage: flag('data-row-menu-page'),
        isFile: flag('data-row-menu-file'),
        forkable: flag('data-row-menu-forkable'),
        forkReason: attr('data-row-menu-fork-reason'),
        muted: flag('data-row-menu-muted'),
        mcpDropped: flag('data-row-menu-mcp-dropped'),
        mcpServers: attr('data-row-menu-mcp-servers'),
        agentUpdateReady: flag('data-row-menu-update-ready'),
        agentUpdateRunning: attr('data-row-menu-update-running'),
        agentUpdateInstalled: attr('data-row-menu-update-installed'),
        updateBusy: flag('data-row-menu-update-busy'),
        updateBusyReason: attr('data-row-menu-update-busy-reason'),
        swarmRank: attr('data-row-menu-swarm-rank'),
    };
}

export type RowMenuType = 'session' | 'browser' | 'page' | 'file' | 'layout';

export const ROW_MENU_TYPES: ReadonlySet<string> = new Set<RowMenuType>(['session', 'browser', 'page', 'file', 'layout']);

export function rowMenuType(c: Partial<RowMenuCtx>): RowMenuType {
    if (c.kind === 'layout') return 'layout';
    if (c.kind === 'browser') return c.isFile ? 'file' : c.isPage ? 'page' : 'browser';
    return 'session';
}
