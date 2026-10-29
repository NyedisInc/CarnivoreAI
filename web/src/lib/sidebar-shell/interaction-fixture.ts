import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { flushSync } from 'svelte';
import { loadLegacyDrawer, paintDrawer, type LegacyWindow } from './legacy-fixture';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

const INTERACTION_SCRIPTS: readonly string[] = [
    'session-sidebar-rename.js', 'session-sidebar-chrome-clicks.js', 'session-sidebar-group-actions.js',
];

export type Event = [string, ...unknown[]];

interface FakeGroup {
    group_uuid: string;
    name: string;
    position: number;
    members: string[];
    colour: string;
}

function startGroups(): FakeGroup[] {
    return [
        { group_uuid: 'g1', name: 'work stuff', position: 0, members: ['cloude_b'], colour: 'violet' },
        { group_uuid: 'g2', name: 'empty one', position: 1, members: ['cloude_a'], colour: 'teal' },
        { group_uuid: 'g3', name: 'last crew', position: 2, members: ['cloude_c'], colour: 'gold' },
    ];
}

export interface RunOptions {
    failRoute?: string;
    confirm?: boolean;
}

export interface Harness {
    w: LegacyWindow;
    list: HTMLElement;
    events: Event[];
    rows: Record<string, unknown>[];
    groups(): FakeGroup[];
}

let w: LegacyWindow;
let list: HTMLElement;
let events: Event[] = [];
let groups: FakeGroup[] = [];
let opts: RunOptions = {};

export function row(name: string, over: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        name, label: name.replace('cloude_', ''), created_by_cloude: true, status: 'idle',
        unread: false, is_pinned: false, project_id: 10, project_name: 'ProjectFoo',
        session_id: `ses_${name}`, session_uuid: `su-${name}`, kind: 'agent', ...over,
    };
}

function startRows(): Record<string, unknown>[] {
    return [
        row('cloude_a'),
        row('cloude_b', { status: 'working' }),
        row('cloude_c', { project_id: 20, project_name: 'Studio' }),
        row('cloude_d', { project_id: 20, project_name: 'Studio', asleep: true }),
        row('cloude_e', { project_id: 20, project_name: 'Studio', session_id: null }),
    ];
}

function body(extra: Record<string, unknown> = {}): Record<string, unknown> {
    return { status: 'ok', groups: groups.map((g) => ({ ...g, members: g.members.slice() })), ...extra };
}

function route(name: string, ...args: unknown[]): void {
    events.push(['api', name, ...args]);
    if (opts.failRoute === name) throw new Error(`${name} refused by the test`);
}

function fakeApi(): Record<string, (...a: any[]) => Promise<unknown>> {
    return {
        listSessionGroups: async () => { route('listSessionGroups'); return body(); },
        renameSessionGroup: async (uuid: string, name: string) => {
            route('renameSessionGroup', uuid, name);
            groups.find((g) => g.group_uuid === uuid)!.name = name;
            return body();
        },
        reorderSessionGroups: async (order: string[]) => {
            route('reorderSessionGroups', order);
            groups.sort((a, b) => order.indexOf(a.group_uuid) - order.indexOf(b.group_uuid));
            return body();
        },
        deleteSessionGroup: async (uuid: string) => {
            route('deleteSessionGroup', uuid);
            const gone = groups.find((g) => g.group_uuid === uuid)!;
            groups = groups.filter((g) => g !== gone);
            return body({ freed: gone.members.length });
        },
        updateProject: async (name: string, o: unknown) => { route('updateProject', name, o); return {}; },
        archiveProject: async (name: string) => { route('archiveProject', name); return {}; },
        sleepSession: async (uuid: string) => { route('sleepSession', uuid); return { status: 'asleep' }; },
        destroySession: async (id: string) => { route('destroySession', id); return {}; },
        destroyExternalSession: async (name: string) => { route('destroyExternalSession', name); return {}; },
        deleteSessionRecord: async (uuid: string) => { route('deleteSessionRecord', uuid); return {}; },
    };
}

export function loadInteractions(sidebarShell: unknown): LegacyWindow {
    const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
    proto.showPopover ??= function () {};
    proto.hidePopover ??= function () {};
    w = loadLegacyDrawer();
    if (w.__legacyInteractionsLoaded) return w;
    list = document.createElement('div');
    list.id = 'session-sidebar-list';
    list.className = 'session-sidebar-list';
    document.body.appendChild(list);
    const live = document.createElement('div');
    live.id = 'session-sidebar-live';
    document.body.appendChild(live);
    w.SessionSidebarReorder = { announce(text: string) { live.textContent = text; }, afterRender() {} };
    const log = console.log;
    console.log = () => {};
    try {
        for (const file of INTERACTION_SCRIPTS) {
            new Function(fs.readFileSync(path.join(repoRoot, 'client', 'js', file), 'utf8'))();
        }
    } finally {
        console.log = log;
    }
    w.SessionSidebarGroupActions.init();
    const text = Object.getOwnPropertyDescriptor(Node.prototype, 'textContent')!;
    Object.defineProperty(live, 'textContent', {
        get() { return text.get!.call(live); },
        set(v: string) { events.push(['live', v]); text.set!.call(live, v); },
    });
    const ctrl: Record<string, any> = {
        listEl: list, _rows: [], _listing: { ok: true }, _lastSig: null, _dragging: false,
        repaint() { paintDrawer(ctrl); },
        async _fetchAndRender() { events.push(['refetch']); ctrl._lastSig = null; ctrl.repaint(); },
    };
    w.SessionSidebar = ctrl;
    list.addEventListener('click', (e) => {
        if (w.SessionSidebarChromeClicks.claim(ctrl, e)) return;
        w.SessionSidebarRename.onListClick(e);
    });
    w.API = fakeApi();
    w.App = {
        showConfirmModal: async (...args: unknown[]) => { events.push(['confirm', ...args]); return opts.confirm !== false; },
    };
    w.WriteFailureNotice = { report(text: string) { events.push(['failure', text]); } };
    w.SessionRowMenuSleep = { releaseThisTab(o: { name: string }) { events.push(['release', o.name]); } };
    w.SessionSidebarGroupColour.open = (anchor: Element, uuid: string) => events.push(['colour-picker', anchor.getAttribute('data-group-menu'), uuid]);
    w.SessionSidebarGroupIcon.open = (anchor: Element, uuid: string) => events.push(['icon-picker', anchor.getAttribute('data-group-menu'), uuid]);
    w.CloudeWeb = {
        layouts: { list: () => [], get: () => null, isUnavailable: () => false },
        sidebarShell,
        openBlueprintsScreen: () => events.push(['blueprints']),
    };
    w.__legacyInteractionsLoaded = true;
    return w;
}

export function startRun(o: RunOptions = {}): Harness {
    opts = o;
    w.SessionSidebarGroupActions.closeMenu();
    w.SessionSidebarStore.save([], [], [], {}, {});
    groups = startGroups();
    w.SessionSidebarGroupStore.apply(body());
    const rows = startRows();
    w.SessionSidebar._rows = rows;
    w.SessionSidebar._lastSig = null;
    w.SessionSidebar.repaint();
    events = [];
    return { w, list, events, rows, groups: () => groups };
}

export async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) {
        await new Promise((r) => setTimeout(r, 0));
        flushSync();
    }
}

export function recorded(): Event[] {
    return events;
}
