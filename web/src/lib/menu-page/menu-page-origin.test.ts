/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi, type Mock } from 'vitest';
import { MENU_PAGES } from './menu-pages';
import { backFromMenuPage, initMenuPageShell, resetMenuPageShell, type ShellDeps } from './menu-page-shell.svelte';
import { clearOrigins } from './menu-page-origin';

let stop: () => void = () => {};
let deps: ShellDeps;
let drawer: { open: boolean; tab: string };
let gen: number;
let openDrawer: Mock<() => void>;
let selectTab: Mock<(tab: string) => void>;

const settle = async (): Promise<void> => {
    await Promise.resolve();
    await Promise.resolve();
};

function mountPage(id: string): void {
    const page = MENU_PAGES.find((p) => p.id === id)!;
    document.getElementById(page.containerId)!.append(document.createElement('div'));
}

const up = (): string[] =>
    MENU_PAGES.filter((p) => document.getElementById(p.containerId)!.firstElementChild).map((p) => p.id);

beforeEach(() => {
    resetMenuPageShell();
    clearOrigins();
    drawer = { open: false, tab: 'sessions' };
    gen = 0;
    for (const page of MENU_PAGES) {
        const div = document.createElement('div');
        div.id = page.containerId;
        document.body.append(div);
    }
    const ns: Record<string, unknown> = {};
    for (const page of MENU_PAGES) {
        ns[page.closer] = () => document.getElementById(page.containerId)!.replaceChildren();
        ns[page.closer.replace(/^close/, 'open')] = () => mountPage(page.id);
    }
    openDrawer = vi.fn<() => void>(() => {
        drawer.open = true;
    });
    selectTab = vi.fn<(tab: string) => void>((tab) => {
        drawer.tab = tab;
    });
    deps = {
        selectTab,
        web: () => ns,
        openDrawer,
        hashEnv: {
            location: { hash: '', pathname: '/', search: '' },
            history: { pushState: () => {}, replaceState: () => {}, back: () => {}, state: null },
        },
        origin: { drawerTab: () => (drawer.open ? drawer.tab : null), generation: () => gen },
    };
    stop = initMenuPageShell(document, deps);
});

afterEach(() => {
    stop();
    document.body.replaceChildren();
});

test('a page opened from the drawer goes back to the drawer on the tab it was showing', async () => {
    drawer = { open: true, tab: 'sessions' };
    mountPage('plugins');
    await settle();
    drawer.open = false;
    selectTab.mockClear();
    backFromMenuPage(document, deps);
    await settle();
    expect(up()).toEqual([]);
    expect(openDrawer).toHaveBeenCalledOnce();
    expect(selectTab).toHaveBeenCalledWith('sessions');
});

test('a chain of pages unwinds in order, then ends at the drawer', async () => {
    drawer = { open: true, tab: 'menu' };
    mountPage('settings');
    await settle();
    drawer.open = false;
    mountPage('plugins');
    await settle();
    expect(up()).toEqual(['plugins']);
    backFromMenuPage(document, deps);
    await settle();
    expect(up()).toEqual(['settings']);
    expect(openDrawer).not.toHaveBeenCalled();
    backFromMenuPage(document, deps);
    await settle();
    expect(up()).toEqual([]);
    expect(openDrawer).toHaveBeenCalledOnce();
});

test('a moved navigation generation takes the terminal path and the drawer stays shut', async () => {
    drawer = { open: true, tab: 'menu' };
    mountPage('plugins');
    await settle();
    drawer.open = false;
    gen += 1;
    backFromMenuPage(document, deps);
    await settle();
    expect(up()).toEqual([]);
    expect(openDrawer).not.toHaveBeenCalled();
});

test('a page opened with no drawer and no page under it goes back to the terminal', async () => {
    mountPage('mods');
    await settle();
    backFromMenuPage(document, deps);
    await settle();
    expect(up()).toEqual([]);
    expect(openDrawer).not.toHaveBeenCalled();
});

test('a page opened after the terminal has been showing for a while starts a fresh chain', async () => {
    vi.useFakeTimers({ toFake: ['performance'] });
    try {
        drawer = { open: true, tab: 'menu' };
        mountPage('plugins');
        await settle();
        drawer.open = false;
        document.getElementById('plugins-screen')!.replaceChildren();
        await settle();
        vi.advanceTimersByTime(2000);
        mountPage('mods');
        await settle();
        backFromMenuPage(document, deps);
        expect(up()).toEqual([]);
        expect(openDrawer).not.toHaveBeenCalled();
    } finally {
        vi.useRealTimers();
    }
});

test('back pops the page entry the shell pushed instead of closing and leaving a twin entry', async () => {
    const env = {
        location: { hash: '', pathname: '/', search: '' },
        history: {
            pushState: vi.fn(() => {
                env.location.hash = '#plugins';
            }),
            replaceState: vi.fn(),
            back: vi.fn(),
            state: null,
        },
    };
    deps = { ...deps, hashEnv: env };
    stop();
    resetMenuPageShell();
    stop = initMenuPageShell(document, deps);
    mountPage('plugins');
    await settle();
    expect(env.history.pushState).toHaveBeenCalledTimes(1);
    backFromMenuPage(document, deps);
    expect(env.history.back).toHaveBeenCalledTimes(1);
    expect(env.history.replaceState).not.toHaveBeenCalled();
});
