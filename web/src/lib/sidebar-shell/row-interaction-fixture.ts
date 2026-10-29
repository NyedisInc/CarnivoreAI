import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { flushSync } from 'svelte';
import { timerChip } from '../timers/timers';
import { loadLegacyDrawer, paintDrawer, type LegacyWindow } from './legacy-fixture';
import * as Clicks from '../drawer/clicks';
import * as Density from '../drawer/density';
import { watchKeepAwakeRepaint } from '../drawer/keep-awake-repaint';
import { publishRunTable } from '../item-menu/run';
import { rowMenuBridge } from '../item-menu/row-bridge';
import { closeRowMenu, installRowMenuOpener } from '../item-menu/row-open';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

const ROW_INTERACTION_SCRIPTS: readonly string[] = [
    'navigation-generation.js',
];

export type Event = [string, ...unknown[]];

export const ROW_PX = 24;

let w: LegacyWindow;
let list: HTMLElement;
let events: Event[] = [];
const kept: Record<string, boolean> = {};

export function row(name: string, over: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        name, label: name.replace('cloude_', ''), created_by_cloude: true, status: 'idle', unread: false,
        is_pinned: false, project_id: 10, project_name: 'ProjectFoo', session_id: `ses_${name}`,
        session_uuid: `su-${name}`, kind: 'agent', agent_family: 'claude', ...over,
    };
}

function startRows(): Record<string, unknown>[] {
    return [
        row('cloude_a', { subagents_running: 2, timers_live: 1, spectator_expires_at: '2026-10-01T12:00:00Z' }),
        row('cloude_b', { status: 'working' }),
        row('cloude_c'),
        row('cloude_d', { status: 'dead' }),
        row('cloude_x', { created_by_cloude: false, session_id: null }),
        row('cloude_z', { status: 'asleep', asleep: true }),
    ];
}

export function rec<T>(name: string, answer: T): (...a: unknown[]) => Promise<T> {
    return async (...a: unknown[]) => {
        events.push([name, ...a.map((x) => (x instanceof Element ? `<${x.className}>` : x))]);
        return answer;
    };
}

function stubLayout(): void {
    const proto = Element.prototype as unknown as { getBoundingClientRect(): DOMRect };
    proto.getBoundingClientRect = function (this: Element): DOMRect {
        const all = Array.from(document.querySelectorAll('#session-sidebar-list .session-sidebar-row'));
        const i = all.indexOf(this);
        if (i >= 0) return { top: i * ROW_PX, bottom: (i + 1) * ROW_PX, height: ROW_PX, left: 0, right: 300, width: 300, x: 0, y: i * ROW_PX, toJSON() {} } as DOMRect;
        const rows = Array.from(this.querySelectorAll('.session-sidebar-row')).map((r) => all.indexOf(r)).filter((n) => n >= 0);
        const top = rows.length ? Math.min(...rows) * ROW_PX : 0;
        const bottom = rows.length ? (Math.max(...rows) + 1) * ROW_PX : 0;
        return { top, bottom, height: bottom - top, left: 0, right: 300, width: 300, x: 0, y: top, toJSON() {} } as DOMRect;
    };
}

export function loadRowInteractions(sidebarShell: unknown): LegacyWindow {
    // jsdom has no popover API; the one item menu's driver (CascadeMenu) shows its levels through it.
    const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
    proto.showPopover ??= function () {};
    proto.hidePopover ??= function () {};
    w = loadLegacyDrawer();
    if (w.__rowInteractionsLoaded) return w;
    list = document.createElement('div');
    list.id = 'session-sidebar-list';
    list.className = 'session-sidebar-list';
    const panel = document.createElement('div');
    panel.className = 'session-sidebar-panel session-sidebar-panel--open';
    panel.appendChild(list);
    document.body.appendChild(panel);
    const live = document.createElement('div');
    live.id = 'session-sidebar-live';
    document.body.appendChild(live);
    const log = console.log;
    console.log = () => {};
    try {
        for (const file of ROW_INTERACTION_SCRIPTS) {
            new Function(fs.readFileSync(path.join(repoRoot, 'client', 'js', file), 'utf8'))();
        }
    } finally {
        console.log = log;
    }
    publishRunTable(globalThis as unknown as Record<string, unknown>);
    installRowMenuOpener();
    stubLayout();
    const g = globalThis as { CSS?: { escape?(v: string): string } };
    if (!g.CSS || typeof g.CSS.escape !== 'function') {
        g.CSS = { ...(g.CSS || {}), escape: (v: string) => String(v).replace(/["\\\]\[]/g, '\\$&') };
    }
    const ctrl: Record<string, any> = {
        listEl: list, _rows: [], _listing: { ok: true }, _lastSig: null, _dragging: false,
        _activeTmuxName: null, _pendingSelection: null,
        repaint() { paintDrawer(ctrl); },
        setDragging(on: boolean) {
            if (!!on === !!ctrl._dragging) return;
            ctrl._dragging = !!on;
            ctrl.repaint();
        },
        async _fetchAndRender() { events.push(['refetch']); ctrl._lastSig = null; ctrl.repaint(); },
        _closeAfterSwitch() { events.push(['close-after-switch']); },
        activateRow(rowEl: Element) { return Clicks.activateRow(ctrl as never, rowEl); },
        close() { events.push(['close']); },
    };
    w.SessionSidebar = ctrl;
    watchKeepAwakeRepaint(() => ctrl.repaint());
    list.addEventListener('click', (e) => { void Clicks.onRowClick(ctrl as never, e); });
    Density.setMode('cozy');
    w.PreferenceBridge = { read: () => undefined };
    w.SessionSidebarGroupOrder = { commitMemberOrder: rec('groups.commitMemberOrder', undefined) };
    w.API = {
        getSession: rec('api.getSession', { id: 'x' }),
        adoptSession: rec('api.adoptSession', { session: { id: 'adopted' } }),
        renameSession: rec('api.renameSession', {}),
        destroySession: rec('api.destroySession', {}),
        destroyExternalSession: rec('api.destroyExternalSession', {}),
    };
    w.App = {
        returnToExistingTerminal: rec('app.returnToExistingTerminal', undefined),
        showConfirmModal: rec('app.confirm', true),
    };
    w.SessionRestartPicker = { open: rec('restart-picker.open', null), lastError: () => null };
    w.CloudeWeb = {
        ...(w.CloudeWeb || {}),
        rowMenu: { ...rowMenuBridge, runCplug: rec('plugin.runCplug', undefined) },
        layouts: { list: () => [], get: () => null, isUnavailable: () => false },
        sidebarShell,
        // Published by main.ts on the page; the legacy timer chip reads it.
        timerChip,
        openSubagentList: (el: Element, id: string, name: string) => { events.push(['subagents.open', el.className, id, name]); return true; },
        openTimerList: (el: Element, id: string, name: string) => { events.push(['timers.open', el.className, id, name]); return true; },
        autoSleep: {
            isKeptAwake: (name: string) => (name in kept ? kept[name] : false),
            setKeepAwake: async (name: string, on: boolean) => { events.push(['keep-awake', name, on]); kept[name] = on; },
        },
    };
    window.addEventListener('session-created', (e) => events.push(['session-created', (e as CustomEvent).detail.session]));
    w.__rowInteractionsLoaded = true;
    return w;
}

export function startRowRun(groups: unknown[] = []) {
    w.SessionSidebarStore.save([], [], [], {}, {});
    w.SessionSidebarGroupStore.apply({ status: 'ok', groups });
    const live = document.getElementById('session-sidebar-live');
    if (live) live.textContent = '';
    closeRowMenu();
    for (const k of Object.keys(kept)) delete kept[k];
    kept.cloude_c = true;
    const ctrl = w.SessionSidebar;
    ctrl._rows = startRows();
    ctrl._lastSig = null;
    ctrl._activeTmuxName = null;
    ctrl._pendingSelection = null;
    ctrl.repaint();
    events = [];
    return { w, list, ctrl };
}

export async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) {
        await new Promise((r) => setTimeout(r, 0));
        flushSync();
    }
}

export function rowEvents(): Event[] {
    return events;
}
