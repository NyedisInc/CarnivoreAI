import { runSessionCardAction, sessionCardMenuItems, type SessionCardMenuItem } from '../plugins/session-card-actions';
import type { PluginContext, SessionCardRow } from '../plugins/types';

interface PluginGlobals {
    UIFlags?: { showMarkUnreadControl(): boolean };
    SessionSidebar?: { _lastSig?: unknown; repaint?(): void };
    CloudeWeb?: { runCplugCardAction?(cplugId: string, row: SessionCardRow, context: PluginContext): Promise<boolean> };
}

const g = (): PluginGlobals => globalThis as unknown as PluginGlobals;

export function pluginFlags(): Record<string, boolean> {
    const flags = g().UIFlags;
    return { show_mark_unread_control: flags ? flags.showMarkUnreadControl() : true };
}

export function repaintRows(): void {
    const bar = g().SessionSidebar;
    if (bar && typeof bar.repaint === 'function') {
        bar._lastSig = null;
        bar.repaint();
    }
}

function cardRow(row: Record<string, unknown> | null | undefined): SessionCardRow {
    const r = row ?? {};
    const projectId = r.projectId != null ? r.projectId : r.project_id != null ? r.project_id : null;
    return {
        name: (r.name as string) || '',
        unread: !!r.unread,
        hostKey: ((r.host_key ?? r.hostKey) as string) || null,
        sessionUuid: ((r.sessionUuid ?? r.session_uuid) as string) || null,
        sessionId: (r.sessionId as string) || null,
        projectId: projectId as number | null,
    } as SessionCardRow;
}

export function pluginItemsFor(row: Record<string, unknown> | null | undefined): SessionCardMenuItem[] {
    return sessionCardMenuItems(cardRow(row), { flags: pluginFlags(), refresh: () => {} });
}

function runContext(): PluginContext {
    return { flags: pluginFlags(), refresh: repaintRows } as PluginContext;
}

export function runPluginItem(id: string, ctx: Record<string, unknown>): Promise<boolean> {
    return runSessionCardAction(id, cardRow(ctx), runContext());
}

export function runCplug(cplugId: string, ctx: Record<string, unknown>): Promise<boolean> {
    const run = g().CloudeWeb?.runCplugCardAction;
    if (typeof run !== 'function') {
        console.error(`[item-menu] window.CloudeWeb.runCplugCardAction is missing - "${cplugId}" cannot run`);
        return Promise.resolve(false);
    }
    return Promise.resolve(run(cplugId, cardRow(ctx), runContext()));
}
