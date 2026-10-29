import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const rowDrag = vi.hoisted(() => ({ on: false }));
vi.mock('../sidebar-shell/row-drag', async (orig) => ({
    ...(await orig<typeof import('../sidebar-shell/row-drag')>()), isDragging: () => rowDrag.on,
}));
import { fakeStorage, freshDrawer, type FreshDrawer } from './test-support';

const FIELD = 'drawer_arrangement';
const STORE_KEY = 'carnivore.session.sidebar.arrangement';
const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));
const settle = (): Promise<void> => vi.advanceTimersByTimeAsync(1600).then(() => undefined);
const SLOW = 20000;

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

type Values = Record<string, unknown>;

class Server {
    revision: number;
    values: Values;
    clients: Prefs[] = [];
    writes = 0;
    delay = 0;
    constructor(values: Values = {}) {
        this.revision = values[FIELD] ? 1 : 0;
        this.values = { ...values };
    }
    patch(client: Prefs, name: string, value: unknown, expected: number): { conflict?: { revision: number; values: Values }; revision?: number; values?: Values } {
        if (expected !== this.revision) return { conflict: { revision: this.revision, values: { ...this.values } } };
        this.writes += 1;
        this.revision += 1;
        if (value === null) delete this.values[name];
        else this.values[name] = JSON.parse(JSON.stringify(value));
        for (const other of this.clients) {
            if (other !== client) other.applyRemote({ revision: this.revision, changed: { [name]: this.values[name] ?? null } });
        }
        return { revision: this.revision, values: { ...this.values } };
    }
}

type Prefs = Record<string, any>;

function fakePrefs(server: Server): Prefs {
    const held: { status: string; revision: number; values: Values } = { status: 'not_hydrated', revision: 0, values: {} };
    const fields: Record<string, { state: string }> = {};
    const listeners: Array<(n: string, v: unknown, r: unknown) => void> = [];
    let remote = false;
    const notify = (name: string, value: unknown, record: unknown): void => listeners.forEach((fn) => fn(name, value, record));
    const api: Prefs = {
        HYDRATED: 'hydrated', COMMITTED: 'committed',
        status: () => held.status,
        committedValue: (name: string) => held.values[name],
        subscribe: (fn: (n: string, v: unknown, r: unknown) => void) => { listeners.push(fn); return () => {}; },
        discardLocal: (name: string) => { delete fields[name]; },
        async hydrate() {
            held.status = 'hydrated';
            held.revision = server.revision;
            held.values = JSON.parse(JSON.stringify(server.values));
            return held.status;
        },
        async set(name: string, value: unknown) {
            if (remote) return { status: 'refused' };
            if (held.status !== 'hydrated') return { status: 'refused' };
            fields[name] = { state: 'pending' };
            await sleep(server.delay || 5);
            const out = server.patch(api, name, value, held.revision);
            if (out.conflict) {
                held.revision = out.conflict.revision;
                held.values = out.conflict.values;
                fields[name] = { state: 'conflict' };
                return { status: 'stale_revision' };
            }
            held.revision = out.revision as number;
            held.values = JSON.parse(JSON.stringify(out.values));
            delete fields[name];
            notify(name, held.values[name], { state: 'committed' });
            return { status: 'committed' };
        },
        applyRemote(frame: { revision: number; changed: Values }) {
            if (frame.revision <= held.revision) return;
            held.revision = frame.revision;
            remote = true;
            try {
                for (const [name, value] of Object.entries(frame.changed)) {
                    if (value === null) delete held.values[name];
                    else held.values[name] = value;
                    if (fields[name]) {
                        fields[name] = { state: 'conflict' };
                        continue;
                    }
                    notify(name, value, { state: 'committed' });
                }
            } finally {
                remote = false;
            }
        },
    };
    server.clients.push(api);
    return api;
}

interface Browser {
    d: FreshDrawer;
    prefs: Prefs;
    frames: Array<(frame: unknown) => void>;
    groupRefreshes: number[];
    S: FreshDrawer['Store'];
    tick(rows: Array<{ name: string; session_uuid: string }>): Promise<void>;
}

async function browser(
    server: Server,
    { local = null, withSync = true, projectsOpen = null }: { local?: Record<string, unknown> | null; withSync?: boolean; projectsOpen?: boolean | null } = {},
): Promise<Browser> {
    const seed: Record<string, string> = {};
    if (local) seed[STORE_KEY] = JSON.stringify({ v: 1, collapsed: [], bands: {}, ids: {}, ...local });
    if (projectsOpen !== null) seed['carnivore.session.sidebar.projects.open'] = projectsOpen ? '1' : '0';
    const prefs = fakePrefs(server);
    const frames: Array<(frame: unknown) => void> = [];
    const groupRefreshes: number[] = [];
    const env: Record<string, unknown> = {
        localStorage: fakeStorage(seed),
        Preferences: prefs,
        AppEvents: { isConnected: () => true, subscribe: (fn: (f: unknown) => void) => { frames.push(fn); return () => {}; } },
        API: { listSessionGroups: async () => { groupRefreshes.push(1); return { groups: [] }; } },
    };
    const d = await freshDrawer(env);
    d.Store.load();
    if (withSync) d.Sync.start();
    await prefs.hydrate();
    return {
        d, prefs, frames, groupRefreshes, S: d.Store,
        async tick(rows) {
            d.Rebind.reconcile(rows);
            if (withSync) d.Sync.noteRows(rows);
            await settle();
        },
    };
}

const ROWS = [
    { name: 'carnivore_a', session_uuid: 'U-A' },
    { name: 'carnivore_b', session_uuid: 'U-B' },
    { name: 'carnivore_c', session_uuid: 'U-C' },
];

describe('pure translation', () => {
    it('toServer names sessions by uuid and leaves out a name with none', async () => {
        const P = (await freshDrawer()).Sync;
        const out = P.toServer({ pinned: ['carnivore_a', 'mystery'], order: ['carnivore_b'], ids: { carnivore_a: 'U-A' },
            bands: { 'g:1': ['carnivore_b'] }, collapsed: ['other'] }, ROWS, null);
        expect(out.pinned).toEqual(['U-A']);
        expect(out.order).toEqual(['U-B']);
        expect(out.bands).toEqual({ 'g:1': ['U-B'] });
        expect(out.collapsed).toEqual(['other']);
        expect(out.projects_open).toBeNull();
    });

    it('fromServer holds an unlisted uuid under a placeholder and keeps a local-only name', async () => {
        const P = (await freshDrawer()).Sync;
        const value = P.normalise({ pinned: ['U-A', 'U-GONE'], order: [], bands: {}, collapsed: ['g:1'] })!;
        const out = P.fromServer(value, { pinned: ['mystery'], order: [], ids: {} }, ROWS);
        expect(out.pinned).toEqual(['carnivore_a', '@U-GONE', 'mystery']);
        expect(out.ids['@U-GONE']).toBe('U-GONE');
        expect(out.ids.carnivore_a).toBe('U-A');
        expect(out.collapsed).toEqual(['g:1']);
    });

    it('merge3 keeps every list this device changed and takes theirs for the rest', async () => {
        const P = (await freshDrawer()).Sync;
        const base = P.normalise({ pinned: ['U-A'], order: ['U-A', 'U-B'], collapsed: [] });
        const mine = P.normalise({ pinned: ['U-A', 'U-C'], order: ['U-A', 'U-B'], collapsed: [] })!;
        const theirs = P.normalise({ pinned: ['U-A'], order: ['U-B', 'U-A'], collapsed: ['other'] })!;
        const out = P.merge3(base, mine, theirs);
        expect(out.pinned).toEqual(['U-A', 'U-C']);
        expect(out.order).toEqual(['U-B', 'U-A']);
        expect(out.collapsed).toEqual(['other']);
    });

    it('the section order (#1687) is omitted when absent, carried when held, and merged like any list', async () => {
        const P = (await freshDrawer()).Sync;
        expect('sections' in P.toServer({ pinned: [], order: [], ids: {} }, ROWS, null)).toBe(false);
        const held = P.toServer({ pinned: [], order: [], ids: {}, sections: ['pack', 'pinned'] }, ROWS, null);
        expect(held.sections).toEqual(['pack', 'pinned']);
        expect(P.fromServer(held, {}, ROWS).sections).toEqual(['pack', 'pinned']);
        expect(P.fromServer(P.normalise({ pinned: [], order: [], bands: {}, collapsed: [] })!, {}, ROWS).sections).toBeNull();
        const base = P.normalise({ pinned: [], order: [], collapsed: [] });
        const mine = P.normalise({ pinned: [], order: [], collapsed: [], sections: ['browsers', 'pinned'] })!;
        const theirs = P.normalise({ pinned: ['U-A'], order: [], collapsed: [] })!;
        const out = P.merge3(base, mine, theirs);
        expect(out.sections).toEqual(['browsers', 'pinned']);
        expect(out.pinned).toEqual(['U-A']);
    });

    it('a Layout pin passes through as itself; a Layout in the order or a band is never synced', async () => {
        const P = (await freshDrawer()).Sync;
        const out = P.toServer({ pinned: ['layout:L1', 'carnivore_a'], order: ['layout:L1', 'carnivore_b'],
            bands: { 'g:1': ['layout:L1', 'carnivore_c'] }, ids: {} }, ROWS, null);
        expect(out.pinned).toEqual(['layout:L1', 'U-A']);
        expect(out.order).toEqual(['U-B']);
        expect(out.bands).toEqual({ 'g:1': ['U-C'] });
        const back = P.fromServer(P.normalise({ pinned: ['layout:L1'], order: [], bands: {}, collapsed: [] })!, {}, ROWS);
        expect(back.pinned).toEqual(['layout:L1']);
        expect(back.ids['layout:L1']).toBe('layout:L1');
    });
});

describe('two browsers', () => {
    it('the first browser migrates its own pins; the second shows them, the server winning', async () => {
        const server = new Server();
        const a = await browser(server, { local: { pinned: ['carnivore_a'], order: ['carnivore_b', 'carnivore_a'], ids: { carnivore_a: 'U-A', carnivore_b: 'U-B' } } });
        await a.tick(ROWS);
        expect((server.values[FIELD] as Values).pinned).toEqual(['U-A']);
        expect((server.values[FIELD] as Values).order).toEqual(['U-B', 'U-A']);
        const b = await browser(server, { local: { pinned: ['carnivore_c'], order: [], ids: { carnivore_c: 'U-C' } } });
        await b.tick(ROWS);
        expect(b.S.current().pinned).toEqual(['carnivore_a']);
        expect(b.S.current().order).toEqual(['carnivore_b', 'carnivore_a']);
        expect(server.writes, 'the second browser must not overwrite what the server already holds').toBe(1);
    }, SLOW);

    it('a browser with nothing of its own writes nothing on an empty server', async () => {
        const server = new Server();
        const a = await browser(server);
        await a.tick(ROWS);
        expect(server.writes).toBe(0);
        expect(server.values[FIELD]).toBeUndefined();
    }, SLOW);

    it('a pin, a reorder and a fold in one browser reach the other live', async () => {
        const server = new Server();
        const a = await browser(server);
        const b = await browser(server);
        await a.tick(ROWS);
        await b.tick(ROWS);
        a.S.save(['carnivore_b'], ['carnivore_c', 'carnivore_a'], ['other']);
        await settle();
        expect(b.S.current().pinned).toEqual(['carnivore_b']);
        expect(b.S.current().order).toEqual(['carnivore_c', 'carnivore_a']);
        expect(b.S.current().collapsed).toEqual(['other']);
        a.S.saveBandOrder('g:grp', ['carnivore_c', 'carnivore_b']);
        await settle();
        expect(b.S.current().bands['g:grp']).toEqual(['carnivore_c', 'carnivore_b']);
    }, SLOW);

    it('NEGATIVE CONTROL: a browser without the sync keeps its own pins', async () => {
        const server = new Server();
        const a = await browser(server);
        const b = await browser(server, { withSync: false, local: { pinned: ['carnivore_c'], order: [], ids: {} } });
        await a.tick(ROWS);
        a.S.save(['carnivore_b'], [], []);
        await settle();
        expect(b.S.current().pinned).toEqual(['carnivore_c']);
    }, SLOW);

    it('a rename the rebind carries moves no uuid and writes nothing', async () => {
        const server = new Server();
        const a = await browser(server, { local: { pinned: ['cloude_a'], order: [], ids: { cloude_a: 'U-A' } } });
        await a.tick([{ name: 'cloude_a', session_uuid: 'U-A' }]);
        const before = server.writes;
        await a.tick([{ name: 'carnivore_a', session_uuid: 'U-A' }]);
        expect(a.S.current().pinned).toEqual(['carnivore_a']);
        expect(server.writes).toBe(before);
    }, SLOW);

    it('an unlisted pin keeps its slot and lands on its row once listed', async () => {
        const server = new Server({ [FIELD]: { v: 1, pinned: ['U-LATE', 'U-A'], order: [], bands: {}, collapsed: [], projects_open: null, mobile: { collapsed: [] } } });
        const b = await browser(server);
        await b.tick(ROWS);
        expect(b.S.current().pinned).toEqual(['@U-LATE', 'carnivore_a']);
        await b.tick(ROWS.concat([{ name: 'carnivore_late', session_uuid: 'U-LATE' }]));
        expect(b.S.current().pinned).toEqual(['carnivore_late', 'carnivore_a']);
        expect(server.writes, 'resolving a placeholder is not a user operation').toBe(0);
    }, SLOW);

    it('a stale write replays this device change on theirs and says so', async () => {
        const server = new Server();
        const a = await browser(server);
        const b = await browser(server);
        await a.tick(ROWS);
        await b.tick(ROWS);
        b.prefs.applyRemote = () => {};
        a.S.save(['carnivore_a'], [], []);
        await settle();
        b.S.save([], ['carnivore_c', 'carnivore_b'], []);
        await settle();
        expect((server.values[FIELD] as Values).pinned, 'the other device pin survives').toEqual(['U-A']);
        expect((server.values[FIELD] as Values).order, 'this device order is replayed').toEqual(['U-C', 'U-B']);
        expect(b.S.current().pinned).toEqual(['carnivore_a']);
    }, SLOW);

    it('the PROJECTS fold is shared, and absent never overwrites it', async () => {
        const server = new Server();
        const a = await browser(server, { projectsOpen: false });
        await a.tick(ROWS);
        expect((server.values[FIELD] as Values).projects_open).toBe(false);
        const b = await browser(server);
        await b.tick(ROWS);
        expect(b.d.GroupStore.isProjectsOpen()).toBe(false);
        b.S.save(['carnivore_a'], [], []);
        await settle();
        expect((server.values[FIELD] as Values).projects_open, 'a pin must not reset the fold to a default').toBe(false);
        b.d.GroupStore.setProjectsOpen(true);
        await settle();
        expect((server.values[FIELD] as Values).projects_open).toBe(true);
        expect(a.d.GroupStore.isProjectsOpen()).toBe(true);
    }, SLOW);

    it('a group write elsewhere re-reads the groups; another frame does not', async () => {
        const server = new Server();
        const a = await browser(server);
        a.frames.forEach((fn) => fn({ type: 'sessions.changed', reason: 'created' }));
        expect(a.groupRefreshes.length).toBe(0);
        a.frames.forEach((fn) => fn({ type: 'sessions.changed', reason: 'groups' }));
        expect(a.groupRefreshes.length).toBe(1);
    }, SLOW);

    it('while the events socket is down, each poll tick re-reads the block itself', async () => {
        const server = new Server();
        const a = await browser(server);
        const b = await browser(server);
        await a.tick(ROWS);
        await b.tick(ROWS);
        b.prefs.applyRemote = () => {};
        (b.d.env.AppEvents as { isConnected: () => boolean }).isConnected = () => false;
        a.S.save(['carnivore_c'], [], []);
        await settle();
        expect(b.S.current().pinned, 'the frame was lost').toEqual([]);
        await b.tick(ROWS);
        expect(b.S.current().pinned).toEqual(['carnivore_c']);
        expect(b.groupRefreshes.length).toBeGreaterThanOrEqual(1);
    }, SLOW);

    it('a change from another device during a drag is not lost, nor overwritten on the drop', async () => {
        const server = new Server();
        const a = await browser(server);
        const b = await browser(server);
        await a.tick(ROWS);
        await b.tick(ROWS);
        rowDrag.on = true;
        a.S.save(['carnivore_c'], [], []);
        await settle();
        b.S.save([], ['carnivore_b', 'carnivore_a'], []);
        rowDrag.on = false;
        await settle();
        await settle();
        expect((server.values[FIELD] as Values).pinned, 'the other device pin must survive the drop').toEqual(['U-C']);
        expect((server.values[FIELD] as Values).order, 'the drop itself must land').toEqual(['U-B', 'U-A']);
        expect(b.S.current().pinned).toEqual(['carnivore_c']);
    }, SLOW);

    it('a PROJECTS toggle made while a save is in flight is the one that sticks', async () => {
        const server = new Server();
        server.delay = 400;
        const a = await browser(server);
        await a.tick(ROWS);
        a.d.GroupStore.setProjectsOpen(false);
        await vi.advanceTimersByTimeAsync(600);
        a.d.GroupStore.setProjectsOpen(true);
        await settle();
        await settle();
        expect((server.values[FIELD] as Values).projects_open).toBe(true);
    }, SLOW);

    it('the section order is ONE value: a drag on one device lands on the other (#1687)', async () => {
        const server = new Server({ [FIELD]: { v: 1, pinned: [], order: [], bands: {}, collapsed: [], projects_open: null } });
        const desktop = await browser(server);
        const phone = await browser(server);
        phone.d.ViewClass.setViewClassSource(() => 'mobile');
        await desktop.tick(ROWS);
        await phone.tick(ROWS);
        expect(desktop.S.current().sections).toBeUndefined();
        desktop.S.saveSectionOrder(['browsers', 'pack', 'pinned', 'layouts', 'groups', 'companies', 'rogue', 'terminals']);
        await settle();
        const stored = (server.values[FIELD] as Values).sections as string[];
        expect(stored.length).toBe(8);
        expect(stored[0]).toBe('browsers');
        await settle();
        expect(phone.S.current().sections).toEqual(stored);
        phone.S.toggleCollapsed('p:7');
        await settle();
        expect((server.values[FIELD] as Values).sections).toEqual(stored);
    }, SLOW);

    it('a phone and a desktop keep their own folds and share their pins', async () => {
        const server = new Server({ [FIELD]: { v: 1, pinned: [], order: [], bands: {}, collapsed: ['companies'], projects_open: null } });
        const desktop = await browser(server);
        const phone = await browser(server);
        phone.d.ViewClass.setViewClassSource(() => 'mobile');
        await desktop.tick(ROWS);
        await phone.tick(ROWS);
        const stored = (): Values => server.values[FIELD] as Values;
        expect(server.writes).toBe(1);
        expect(stored().mobile).toEqual({ collapsed: ['companies'] });
        expect(phone.S.isCollapsed('companies')).toBe(true);
        expect(desktop.S.isCollapsed('companies')).toBe(true);
        phone.S.toggleCollapsed('p:7');
        await settle();
        expect(stored().collapsed).toEqual(['companies']);
        expect(stored().mobile).toEqual({ collapsed: ['companies', 'p:7'] });
        expect(phone.S.viewCollapsed()).toEqual(['companies', 'p:7']);
        expect(desktop.S.isCollapsed('p:7')).toBe(false);
        expect(desktop.S.viewCollapsed()).toEqual(['companies']);
        desktop.S.toggleCollapsed('g:x');
        await settle();
        expect(stored().collapsed).toEqual(['companies', 'g:x']);
        expect(stored().mobile).toEqual({ collapsed: ['companies', 'p:7'] });
        expect(phone.S.isCollapsed('g:x')).toBe(false);
        desktop.S.save(['carnivore_a'], ['carnivore_a']);
        await settle();
        expect(phone.S.current().pinned).toEqual(['carnivore_a']);
        expect(phone.S.viewCollapsed()).toEqual(['companies', 'p:7']);
        const win = Object.assign(new EventTarget(), { innerWidth: 1024 });
        vi.stubGlobal('window', win);
        try {
            const c = await browser(server);
            await c.tick(ROWS);
            expect(c.d.ViewClass.viewClass()).toBe('desktop');
            expect(c.S.isCollapsed('g:x')).toBe(true);
            const repaint = vi.fn();
            c.d.ViewClass.watchViewClass(repaint);
            const writes = server.writes;
            win.innerWidth = 600;
            win.dispatchEvent(new Event('resize'));
            expect(repaint).toHaveBeenCalledWith('mobile');
            expect(c.S.isCollapsed('p:7')).toBe(true);
            expect(c.S.isCollapsed('g:x')).toBe(false);
            win.innerWidth = 0;
            win.dispatchEvent(new Event('resize'));
            expect(repaint, 'a width of 0 is no viewport, the class is kept').toHaveBeenCalledTimes(1);
            win.innerWidth = 1200;
            win.dispatchEvent(new Event('resize'));
            expect(repaint).toHaveBeenCalledTimes(2);
            expect(c.S.isCollapsed('g:x')).toBe(true);
            await settle();
            expect(server.writes, 'crossing the line must not write').toBe(writes);
        } finally {
            vi.unstubAllGlobals();
        }
    }, SLOW);
});
