/** @vitest-environment jsdom */
import * as Clicks from './clicks';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeAll, beforeEach, describe, it, vi } from 'vitest';
import { SessionSidebarController } from './controller';
import { setDrawerEnv } from './env';
import { fakeStorage } from './test-support';
import { readLastView } from './last-view';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
type Win = Record<string, any>;
const win = globalThis as unknown as Win;

function loadClassic(file: string): void {
    const log = console.log;
    console.log = () => {};
    try {
        new Function(fs.readFileSync(path.join(repoRoot, 'client', 'js', file), 'utf8'))();
    } finally {
        console.log = log;
    }
}

afterEach(() => {
    vi.restoreAllMocks();
    document.body.replaceChildren();
});

describe('closing the drawer releases focus (from test_session_sidebar_focus_release)', () => {
    function makeSandbox({ supportsInert = true } = {}) {
        vi.spyOn(SessionSidebarController, 'SUPPORTS_INERT', 'get').mockReturnValue(supportsInert);
        const panel = document.createElement('aside');
        const row = document.createElement('button');
        const listEl = document.createElement('div');
        panel.append(listEl, row);
        const toggleBtn = document.createElement('button');
        const backdrop = document.createElement('div');
        document.body.append(panel, toggleBtn, backdrop);
        const ctrl = new SessionSidebarController();
        ctrl.panel = panel;
        ctrl.backdrop = backdrop;
        ctrl.toggleBtn = toggleBtn;
        ctrl.listEl = listEl;
        ctrl._fetchAndRender = async () => {};
        ctrl._startPoll = () => {};
        return { ctrl, panel, row, toggleBtn };
    }

    it('closing the bar takes focus off a row inside it', () => {
        const { ctrl, row, toggleBtn } = makeSandbox();
        ctrl.open();
        row.focus();
        assert.equal(document.activeElement, row, 'precondition: the row holds focus');
        ctrl.close();
        assert.notEqual(document.activeElement, row,
            'the off-screen row must not still be document.activeElement - that is '
            + 'the whole bug: its keydown handler eats arrows, Space and `p`');
        assert.equal(document.activeElement, toggleBtn,
            'focus goes somewhere sensible (the control that opens the bar), not nowhere');
    });

    it('a closed bar is inert where the browser supports it', () => {
        const { ctrl, panel } = makeSandbox({ supportsInert: true });
        ctrl.open();
        assert.equal(panel.inert, false, 'an open panel must stay interactive');
        ctrl.close();
        assert.equal(panel.inert, true, 'a closed panel must not be reachable');
        ctrl.open();
        assert.equal(panel.inert, false, 're-opening must give the panel back');
    });

    it('without inert support the blur still happens', () => {
        const { ctrl, row, panel, toggleBtn } = makeSandbox({ supportsInert: false });
        ctrl.open();
        row.focus();
        ctrl.close();
        assert.equal(document.activeElement, toggleBtn, 'focus still leaves the panel');
        // nothing at all
        assert.notEqual(panel.inert, true, 'and no unsupported attribute is asserted');
        assert.equal(panel.hasAttribute('inert'), false);
    });

    it('focus outside the panel is left alone', () => {
        const { ctrl, panel } = makeSandbox();
        const elsewhere = document.createElement('button');
        document.body.append(elsewhere);
        ctrl.open();
        elsewhere.focus();
        ctrl.close();
        assert.equal(document.activeElement, elsewhere, 'an element outside the panel keeps focus through a close');
        assert.equal(panel.inert, true, 'the panel is still made inert either way');
    });
});

describe('a row pick shows at once (from test_sidebar_immediate_selection)', () => {
    beforeAll(() => {
        loadClassic('navigation-generation.js');
    });

    function deferred<T = unknown>() {
        let resolve!: (v: T) => void;
        let reject!: (e: unknown) => void;
        const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
        return { promise, resolve, reject };
    }

    interface FakeRow { dataset: Record<string, string>; selected: boolean; setAttribute(k: string, v: string): void }

    function harness() {
        const requests: Array<{ id: string } & ReturnType<typeof deferred>> = [];
        const alerts: unknown[] = [];
        const entered: string[] = [];
        win.API = {};
        win.CloudeTerminal = { SCROLLBACK_ROWS: 5000 };
        win.App = {};
        win.SessionHeaderLed = { beginRequest() {}, update() {} };
        win.alert = (x: unknown) => alerts.push(x);
        delete win.CloudeWeb;
        const ctrl = new SessionSidebarController();
        win.SessionSidebar = ctrl;
        const rows: FakeRow[] = ['old', 'a', 'b'].map((name) => ({
            dataset: { name, sessionId: name, active: name === 'old' ? '1' : '0' },
            selected: name === 'old',
            setAttribute(key: string, value: string) { if (key === 'aria-selected') this.selected = value === 'true'; },
        }));
        ctrl.listEl = { querySelectorAll: () => rows } as unknown as HTMLElement;
        ctrl._activeTmuxName = 'old';
        ctrl._closeAfterSwitch = () => {};
        ctrl.repaint = () => Clicks.paintSelection(ctrl);
        win.API.getSession = (id: string, opts: { includeScrollback: boolean }) => {
            assert.equal(opts.includeScrollback, true);
            const d = deferred();
            requests.push({ id, ...d });
            return d.promise;
        };
        win.API.adoptSession = (name: string) => {
            const d = deferred();
            requests.push({ id: name, ...d });
            return d.promise;
        };
        win.App.returnToExistingTerminal = (info: { session: { id: string } }) => {
            entered.push(info.session.id);
            ctrl.setActiveSession(info.session.id, info.session.id);
        };
        return { ctrl, rows, requests, alerts, entered };
    }

    it('name click highlights and starts network synchronously, retaining actual input/action identity', async () => {
        const { ctrl, rows, requests } = harness();
        const target = { closest: (selector: string) => (selector === '.session-sidebar-row' ? rows[1] : null) };
        const run = Clicks.onRowClick(ctrl, { target, detail: 1 } as never);
        assert.equal(requests.length, 1);
        assert.equal(rows[1]!.selected, true);
        assert.equal(rows[0]!.selected, false);
        assert.equal(ctrl._activeTmuxName, 'old');
        assert.equal(rows[0]!.dataset.active, '1');
        assert.equal(rows[1]!.dataset.active, '0');
        requests[0]!.resolve({ session: { id: 'a' } });
        await run;
        assert.equal(ctrl._activeTmuxName, 'a');
    });

    it('failed selection restores attached row; stale failure cannot roll back newer selection or alert', async () => {
        const { ctrl, rows, requests, alerts } = harness();
        const a = ctrl.activateRow(rows[1] as unknown as Element);
        const b = ctrl.activateRow(rows[2] as unknown as Element);
        requests[0]!.reject(Error('stale'));
        await a;
        assert.equal(rows[2]!.selected, true);
        assert.equal(alerts.length, 0);
        requests[1]!.reject(Error('current'));
        await b;
        assert.equal(rows[0]!.selected, true);
        assert.equal(alerts.length, 1);
    });

    it('adoption failure restores attachment and never promotes the external row', async () => {
        const { ctrl, rows, requests, alerts } = harness();
        delete rows[1]!.dataset.sessionId;
        const run = ctrl.activateRow(rows[1] as unknown as Element);
        assert.equal(rows[1]!.selected, true);
        requests[0]!.reject(Error('adopt refused'));
        await run;
        assert.equal(ctrl._activeTmuxName, 'old');
        assert.equal(rows[0]!.selected, true);
        assert.equal(alerts.length, 1);
    });

    it('clicking original attached row supersedes pending navigation', async () => {
        const { ctrl, rows, requests, entered } = harness();
        const a = ctrl.activateRow(rows[1] as unknown as Element);
        const old = ctrl.activateRow(rows[0] as unknown as Element);
        requests[1]!.resolve({ session: { id: 'old' } });
        await old;
        requests[0]!.resolve({ session: { id: 'a' } });
        await a;
        assert.deepEqual(entered, ['old']);
        assert.equal(rows[0]!.selected, true);
    });

    it('activation uses cached rows; overlapping refreshes coalesce one trailing read with latest attachment', async () => {
        const { ctrl } = harness();
        const d = deferred<{ listing: { ok: boolean }; rows: Array<Record<string, unknown>> }>();
        let fetches = 0;
        ctrl._loader = () => { fetches++; return d.promise; };
        ctrl.isOpen = true;
        ctrl._rows = [{ name: 'old' }, { name: 'a' }];
        const first = ctrl._fetchAndRender();
        const second = ctrl._fetchAndRender();
        const third = ctrl._fetchAndRender();
        ctrl.setActiveSession('a', 'a');
        assert.equal(fetches, 1);
        assert.equal(ctrl._rows[1]!.is_this_tab, true);
        d.resolve({ listing: { ok: true }, rows: [{ name: 'old', is_this_tab: true }, { name: 'a' }] });
        await Promise.all([first, second, third]);
        assert.equal(ctrl._rows[0]!.is_this_tab, false);
        assert.equal(ctrl._rows[1]!.is_this_tab, true);
        assert.equal(fetches, 2);
    });

    it('second click of a double-click shares the pending selection instead of requesting again', async () => {
        const { ctrl, rows, requests } = harness();
        const first = ctrl.activateRow(rows[1] as unknown as Element);
        await ctrl.activateRow(rows[1] as unknown as Element);
        assert.equal(requests.length, 1);
        requests[0]!.resolve({ session: { id: 'a' } });
        await first;
        assert.equal(rows[1]!.selected, true);
    });

    it('pending visual selection does not redirect the attached row destructive action', async () => {
        const { ctrl, rows, requests } = harness();
        const destroyed: string[] = [];
        win.SessionRowActions = { ATTR_NAME: 'name', ATTR_ACTION: 'action', ACTION_CLOSE: 'close' };
        win.TerminalController = { destroySession: async (action: string) => destroyed.push(action) };
        const pending = ctrl.activateRow(rows[1] as unknown as Element);
        await Clicks.onRowActionClick(ctrl, {
            getAttribute: (key: string) => (key === 'name' ? 'old' : 'close'),
            closest: () => rows[0],
        } as never);
        assert.deepEqual(destroyed, ['close']);
        requests[0]!.resolve(null);
        await pending;
    });

    it('killing this tab\'s own session leaves a docked drawer open and its stored choice alone (#1836)', async () => {
        const { ctrl, rows, requests } = harness();
        const closes: unknown[] = [];
        delete (ctrl as unknown as Record<string, unknown>)._closeAfterSwitch;
        ctrl.close = (opts?: { persist?: boolean }) => { closes.push(opts); };
        win.SessionRowActions = { ATTR_NAME: 'name', ATTR_ACTION: 'action', ACTION_CLOSE: 'close' };
        win.TerminalController = { destroySession: async () => {} };
        const btn = {
            getAttribute: (key: string) => (key === 'name' ? 'old' : 'close'),
            closest: () => rows[0],
        };
        const widthWas = window.innerWidth;
        try {
            window.innerWidth = 1400;
            await Clicks.onRowActionClick(ctrl, btn as never);
            assert.deepEqual(closes, [], 'a docked drawer is not closed (that stores "closed" and the sidebar stays folded)');
            window.innerWidth = 600;
            await Clicks.onRowActionClick(ctrl, btn as never);
            assert.equal(closes.length, 1, 'an overlay still gets out of the way');
        } finally {
            window.innerWidth = widthWas;
        }
        void requests;
    });

    it('killing this tab\'s own session keeps the docked layout: open, no icon rail (#1836)', async () => {
        const { ctrl, rows } = harness();
        const panel = document.createElement('aside');
        const toggleBtn = document.createElement('button');
        const backdrop = document.createElement('div');
        document.body.append(panel, toggleBtn, backdrop);
        Object.assign(ctrl, { panel, toggleBtn, backdrop });
        delete (ctrl as unknown as Record<string, unknown>)._closeAfterSwitch;
        ctrl._fetchAndRender = async () => {};
        ctrl._startPoll = () => {};
        win.SessionRowActions = { ATTR_NAME: 'name', ATTR_ACTION: 'action', ACTION_CLOSE: 'close' };
        win.TerminalController = { destroySession: async () => {} };
        const widthWas = window.innerWidth;
        try {
            window.innerWidth = 1400;
            ctrl.open();
            await Clicks.onRowActionClick(ctrl, {
                getAttribute: (key: string) => (key === 'name' ? 'old' : 'close'),
                closest: () => rows[0],
            } as never);
            assert.equal(ctrl.isOpen, true, 'the drawer is still open');
            assert.equal(document.body.classList.contains('session-sidebar-pinned'), true, 'still docked');
            assert.equal(document.body.classList.contains('session-sidebar-railed'), false, 'the icon rail never appears');
            assert.notEqual(localStorage.getItem(SessionSidebarController.STORAGE_KEY), '0', 'no "closed" choice is stored');
        } finally {
            window.innerWidth = widthWas;
            document.body.classList.remove('session-sidebar-pinned', 'session-sidebar-railed');
        }
    });

    it('navigation invalidates a pending listing and refreshes only an open sidebar', async () => {
        const { ctrl } = harness();
        const requests: Array<ReturnType<typeof deferred<{ listing: { ok: boolean }; rows: Array<Record<string, unknown>> }>>> = [];
        ctrl._loader = () => {
            const d = deferred<{ listing: { ok: boolean }; rows: Array<Record<string, unknown>> }>();
            requests.push(d);
            return d.promise;
        };
        ctrl.isOpen = true;
        ctrl._rows = [{ name: 'old' }, { name: 'a' }];
        const pending = ctrl._fetchAndRender();
        ctrl.setActiveSession('a', 'a');
        assert.equal(requests.length, 1, 'navigation itself must not start another concurrent listing');
        requests[0]!.resolve({ listing: { ok: true }, rows: [{ name: 'stale' }] });
        await new Promise((resolve) => setTimeout(resolve, 0));
        assert.equal(requests.length, 2);
        assert.equal(ctrl._rows.some((row) => row.name === 'stale'), false);
        requests[1]!.resolve({ listing: { ok: true }, rows: [{ name: 'a' }] });
        await pending;
        assert.equal(ctrl._rows[0]!.is_this_tab, true);
    });
});

describe('the last main view record (#1542)', () => {
    function bare(layout?: { active: boolean; holds: boolean }) {
        win.SessionHeaderLed = { beginRequest() {}, update() {} };
        setDrawerEnv({
            localStorage: store,
            SessionHeaderLed: win.SessionHeaderLed,
            ...(layout ? { CloudeWeb: { layoutPage: { isActive: () => layout.active, holds: () => layout.holds } } } : {}),
        } as never);
        const ctrl = new SessionSidebarController();
        ctrl._rows = [];
        return ctrl;
    }
    let store = fakeStorage();
    beforeEach(() => { store = fakeStorage(); });
    afterEach(() => setDrawerEnv(null));

    it('writes the attached session, and a (null, null) call keeps it', () => {
        const ctrl = bare();
        ctrl.setActiveSession('ses_a', 'carnivore_a');
        assert.deepEqual(readLastView(), { kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
        ctrl.setActiveSession(null, null);
        assert.deepEqual(readLastView(), { kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
    });

    it('skips a session the on-screen Layout holds, records one it does not', () => {
        bare({ active: true, holds: true }).setActiveSession('ses_a', 'carnivore_a');
        assert.equal(readLastView(), null);
        bare({ active: true, holds: false }).setActiveSession('ses_x', 'carnivore_x');
        assert.deepEqual(readLastView(), { kind: 'session', sessionId: 'ses_x', tmuxName: 'carnivore_x' });
    });
});

describe('forceRefresh repaints past an unchanged poll signature', () => {
    it('clears the signature, then re-reads once', async () => {
        const ctrl = new SessionSidebarController();
        ctrl._lastSig = 'same';
        const seen: Array<string | null> = [];
        ctrl._fetchAndRender = async () => { seen.push(ctrl._lastSig); };
        await ctrl.forceRefresh();
        assert.deepEqual(seen, [null]);
    });
});
