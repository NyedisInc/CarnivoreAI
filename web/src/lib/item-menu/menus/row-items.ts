import type { RowMenuCtx } from '../row-context';

export interface RowItem {
    id: string;
    order: number;
    tone?: 'update';
    danger?: boolean;
    label(ctx: RowMenuCtx): string;
    available(ctx: RowMenuCtx): boolean;
    enabled(ctx: RowMenuCtx): boolean;
    reason(ctx: RowMenuCtx): string;
}

interface ItemGlobals {
    CloudeI18n?: { t(key: string, vars?: Record<string, unknown>): string };
    CloudeWeb?: { autoSleep?: { isKeptAwake(name: string): boolean | null } };
    SessionSidebarStore?: { isPinned(name: string): boolean };
    SessionSidebarLayouts?: { blueprintsEnabled(): boolean };
}

const g = (): ItemGlobals => globalThis as unknown as ItemGlobals;

function tr(key: string, vars?: Record<string, unknown>): string {
    const i18n = g().CloudeI18n;
    return i18n && typeof i18n.t === 'function' ? i18n.t(key, vars) : key;
}

const isSessionless = (c: RowMenuCtx): boolean => c.kind === 'browser' || c.kind === 'layout';

const isRemote = (c: RowMenuCtx): boolean => !!c.hostKey && c.hostKey !== 'local';

const SLEEPABLE_FAMILIES = ['claude', 'codex'];

const SWARM_FAMILIES = ['claude', 'codex'];

function keptAwake(c: RowMenuCtx): boolean | null {
    const store = g().CloudeWeb?.autoSleep;
    return store ? store.isKeptAwake(c.name) : null;
}

const blueprints = (): boolean => !!g().SessionSidebarLayouts?.blueprintsEnabled();

export const GROUP_STARTS: readonly number[] = [0, 100, 190, 400, 500, 700, 900];

export function groupFor(order: number): number {
    let found = 0;
    GROUP_STARTS.forEach((start, i) => {
        if (order >= start) found = i;
    });
    return found;
}

const always = (): boolean => true;
const noReason = (): string => '';

export const ROW_ITEMS: readonly RowItem[] = [
    {
        id: 'update-restart', order: 10, tone: 'update',
        label: (c) => `update and restart (${c.agentUpdateRunning} → ${c.agentUpdateInstalled})`,
        available: (c) => !!c.agentUpdateReady && !!c.restartable && !c.asleep,
        enabled: always, reason: noReason,
    },
    {
        id: 'popout', order: 120,
        label: () => tr('browser.menu.pop_out'),
        available: (c) => c.kind === 'browser' && !c.isFile,
        enabled: always, reason: noReason,
    },
    {
        id: 'restart-now', order: 5, tone: 'update',
        label: () => tr('session.menu.restart_now'),
        available: (c) => c.shiftHeld === true && !!c.restartable && !c.asleep && !c.archived,
        enabled: always, reason: noReason,
    },
    {
        id: 'rename', order: 190,
        label: () => 'rename',
        available: (c) => !c.archived && !c.closed,
        enabled: (c) => !!c.renameable,
        reason: (c) => c.renameReason || 'cannot rename: this agent has no live backend to send the change to',
    },
    {
        id: 'move-to-group', order: 300,
        label: () => 'add to',
        available: (c) => !!c.groupable && isSessionless(c),
        enabled: always, reason: noReason,
    },
    {
        id: 'add-to', order: 300,
        label: () => 'add to',
        available: (c) => !!c.groupable && c.kind !== 'layout' && !isSessionless(c),
        enabled: always, reason: noReason,
    },
    {
        id: 'add-members', order: 300,
        label: () => 'add',
        available: (c) => !!c.groupable && c.kind === 'layout',
        enabled: always, reason: noReason,
    },
    {
        id: 'remove-from-group', order: 320,
        label: () => tr('sidebar.group.remove_from.label'),
        available: (c) => !!c.groupUuid,
        enabled: always, reason: noReason,
    },
    {
        id: 'pin', order: 250,
        label: (c) => {
            const pinned = !!g().SessionSidebarStore?.isPinned(c.name);
            if (c.kind === 'layout') return tr(pinned ? 'layout.row.unpin' : 'layout.row.pin');
            if (isSessionless(c)) return tr(pinned ? 'browser.menu.unpin' : 'browser.menu.pin');
            return pinned ? 'unpin' : 'pin';
        },
        available: always,
        enabled: always, reason: noReason,
    },
    {
        id: 'keep-awake', order: 520,
        label: (c) => tr(keptAwake(c) === true ? 'session.menu.keep_awake.turn_off' : 'session.menu.keep_awake.turn_on'),
        available: (c) => {
            if (isSessionless(c) || isRemote(c) || c.closed) return false;
            const kept = keptAwake(c);
            if (kept === null) return false;
            return kept === true || SLEEPABLE_FAMILIES.includes(c.agentFamily);
        },
        enabled: always, reason: noReason,
    },
    {
        id: 'fork', order: 130,
        label: () => tr('session.fork_to.action'),
        available: (c) => !isSessionless(c) && !c.archived && !c.closed && !isRemote(c),
        enabled: (c) => !!c.forkable,
        reason: (c) => c.forkReason || 'cannot fork: carnivore did not create this agent, so it has no recorded conversation to branch from',
    },
    {
        id: 'new-in-folder', order: 110,
        label: () => 'new agent',
        available: (c) => !isSessionless(c),
        enabled: always, reason: noReason,
    },
    {
        id: 'new-terminal-here', order: 120,
        label: () => 'new terminal here',
        available: (c) => !isSessionless(c),
        enabled: always, reason: noReason,
    },
    {
        id: 'show-path', order: 410,
        label: () => tr('sidebar.show_path.label'),
        available: (c) => !isSessionless(c),
        enabled: always, reason: noReason,
    },
    {
        id: 'copy-session-id', order: 420,
        label: () => tr('session.menu.copy_session_id'),
        available: (c) => !isSessionless(c) && !!c.conversationId,
        enabled: always, reason: noReason,
    },
    {
        id: 'mark-read', order: 195,
        label: () => tr('session.menu.mark_read'),
        available: (c) => !(isSessionless(c) || c.archived || c.closed || c.unread !== true),
        enabled: always, reason: noReason,
    },
    {
        id: 'mute', order: 530,
        label: (c) => (c.muted ? 'unmute' : 'mute'),
        available: (c) => !isSessionless(c),
        enabled: always, reason: noReason,
    },
    {
        id: 'reconnect-mcp', order: 5,
        label: (c) => (c.mcpServers ? tr('mcp.reconnect_named', { servers: c.mcpServers }) : tr('mcp.reconnect')),
        available: (c) => !isSessionless(c) && !isRemote(c) && !c.asleep && c.agentFamily === 'claude' && !!c.mcpDropped,
        enabled: (c) => c.status === 'idle' || c.status === 'finished_unread',
        reason: () => tr('mcp.reconnect_busy'),
    },
    {
        id: 'schedule', order: 510,
        label: () => tr('automations.schedule_this'),
        available: (c) => !isSessionless(c) && !isRemote(c) && !!c.sessionUuid,
        enabled: always, reason: noReason,
    },
    {
        id: 'restart', order: 710,
        label: () => 'restart the agent',
        available: (c) => !!c.restartable && !c.asleep && !c.archived,
        enabled: always, reason: noReason,
    },
    {
        id: 'swarm-join', order: 720,
        label: () => tr('session.menu.swarm_join'),
        available: (c) => !isSessionless(c) && !c.archived && !c.closed && !c.swarmRank && SWARM_FAMILIES.includes(c.agentFamily),
        enabled: (c) => !!c.sessionUuid,
        reason: () => tr('session.swarm.no_uuid'),
    },
    {
        id: 'swarm-leave', order: 720,
        label: () => tr('session.menu.swarm_leave'),
        available: (c) => !isSessionless(c) && !c.archived && !c.closed && c.swarmRank === 'feature',
        enabled: (c) => !!c.sessionUuid,
        reason: () => tr('session.swarm.no_uuid'),
    },
    {
        id: 'sleep', order: 750,
        label: () => tr('session.menu.sleep'),
        available: (c) => !isSessionless(c) && !c.asleep && !c.archived && !c.closed && !isRemote(c),
        enabled: (c) => !!c.sessionUuid,
        reason: () => tr('session.sleep.no_uuid'),
    },
    {
        id: 'send-to', order: 760,
        label: () => tr('session.menu.send_to'),
        available: (c) => !isSessionless(c) && !c.archived && !c.closed && !isRemote(c),
        enabled: (c) => !!c.sessionUuid,
        reason: () => tr('session.send.no_uuid'),
    },
    {
        id: 'move-to-folder', order: 765,
        label: () => tr('session.menu.move_folder'),
        available: (c) => !isSessionless(c) && !c.asleep && !c.archived && !c.closed && !isRemote(c),
        enabled: (c) => !!c.sessionUuid,
        reason: () => tr('session.move.no_uuid'),
    },
    {
        id: 'wake', order: 750,
        label: () => tr('session.menu.wake'),
        available: (c) => !!c.asleep,
        enabled: (c) => !!c.sessionUuid,
        reason: () => tr('session.wake.no_uuid'),
    },
    {
        id: 'reopen', order: 750,
        label: () => tr('session.menu.reopen'),
        available: (c) => !!c.closed,
        enabled: (c) => !!c.sessionUuid,
        reason: () => tr('session.wake.no_uuid'),
    },
    {
        id: 'archive', order: 900,
        label: () => tr('session.archive.action'),
        available: (c) => !!c.closed,
        enabled: (c) => !!c.sessionUuid,
        reason: () => tr('session.archive.failed.no_id'),
    },
    {
        id: 'save-blueprint', order: 330,
        label: () => tr('layout.row.save_blueprint'),
        available: (c) => c.kind === 'layout' && blueprints(),
        enabled: always, reason: noReason,
    },
    {
        id: 'load-blueprint', order: 140,
        label: () => tr('layout.row.load_blueprint'),
        available: (c) => c.kind === 'layout' && blueprints(),
        enabled: always, reason: noReason,
    },
    {
        id: 'colour', order: 340,
        label: () => tr('layout.row.colour.menu'),
        available: (c) => c.kind === 'layout',
        enabled: always, reason: noReason,
    },
    {
        id: 'close', order: 900, danger: true,
        label: (c) => {
            if (c.kind === 'browser') {
                if (c.isFile) return tr('files.menu.close');
                return tr(c.isPage ? 'browser.menu.close_page' : 'browser.menu.close');
            }
            if (c.kind === 'layout') return tr('layout.row.remove');
            return tr('session.menu.kill');
        },
        available: (c) => !c.archived && !c.closed,
        enabled: (c) => !c.asleep || !!c.sessionUuid,
        reason: () => tr('session.wake.no_uuid'),
    },
];
