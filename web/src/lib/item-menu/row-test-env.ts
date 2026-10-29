import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { assignMenuKeys } from '../menu-keys/menu-keys';
import './menus/all';
import { rowMenuItems, type ResolvedRowItem } from './menus/row';
import { itemMenu } from './registry';
import { publishRunTable } from './run';
import { rowMenuBridge } from './row-bridge';
import { rowMenuType, type RowMenuCtx } from './row-context';

export type Win = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export const win = globalThis as unknown as Win;


export function bench(extra: Win = {}, t: (key: string, vars?: Record<string, unknown>) => string = (key) => key): Win {
    win.CloudeI18n = { t };
    win.SessionSidebarLayouts = { blueprintsEnabled: () => true };
    win.CloudeWeb = { rowMenu: rowMenuBridge };
    for (const [k, v] of Object.entries(extra)) {
        if (k === 'CloudeWeb') win.CloudeWeb = { rowMenu: rowMenuBridge, ...(v as Win) };
        else win[k] = v;
    }
    return win;
}

export function loadRunTable(): Win {
    if (win.SessionRowMenuActions) return win;
    const log = console.log;
    console.log = () => {};
    try {
        publishRunTable(win);
    } finally {
        console.log = log;
    }
    if (!win.CSS || typeof win.CSS.escape !== 'function') win.CSS = { ...(win.CSS || {}), escape: (v: string) => String(v) };
    return win;
}

export function ctxOf(over: Partial<RowMenuCtx> & Record<string, unknown>): RowMenuCtx {
    return {
        name: 'cloude_x', label: '', sessionId: null, sessionUuid: '', conversationId: '', asleep: false, archived: false, closed: false,
        projectId: null, surface: 'sidebar', owned: false, status: 'unknown', unread: false, restartable: false, hostKey: 'local',
        agentFamily: '', pluginItems: '', groupable: false, groupUuid: '', groupName: '', renameable: false, renameReason: '',
        forkable: false, forkReason: '', muted: false, mcpDropped: false, mcpServers: '', agentUpdateReady: false,
        agentUpdateRunning: '', agentUpdateInstalled: '', updateBusy: false, updateBusyReason: '',
        ...over,
    } as RowMenuCtx;
}

export type KeyedItem = ResolvedRowItem & { shortcut: string };

export function itemsOf(ctx: RowMenuCtx): KeyedItem[] {
    const items = rowMenuItems(ctx);
    const keys = assignMenuKeys(items.map((i) => ({ id: i.id, label: i.label, skip: !i.enabled })));
    return items.map((i, n) => ({ ...i, shortcut: keys[n] ?? '' }));
}

export const idsOf = (ctx: RowMenuCtx): string[] => rowMenuItems(ctx).map((i) => i.id);

export function nodesOf(ctx: RowMenuCtx, close: () => void = () => {}): MenuNode[] {
    return itemMenu(rowMenuType(ctx), ctx, { close, glyph: () => '' })?.nodes ?? [];
}

export function triggerFrom(html: string): HTMLElement {
    const holder = document.createElement('div');
    holder.innerHTML = html;
    return holder.firstElementChild as HTMLElement;
}
