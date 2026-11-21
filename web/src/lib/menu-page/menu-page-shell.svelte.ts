import { MENU_PAGES, MENU_PAGE_OPEN_CLASS, menuPage, type MenuPage } from './menu-pages';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import { clearPageHash, hashNamesPage, pageOfHash, popPageEntries, pushPageHash, type HashEnv } from './menu-page-hash';
import { initMenuPageEscape } from './menu-page-escape';
import { initMenuPageOutside } from './menu-page-outside';
import { mayClosePage, type ConfirmFn } from './menu-page-dirty';
import { surfaceTrackerFor, type SurfaceTracker } from './menu-page-surface';
import { slideBack } from './menu-page-ghost';
import { noteClosedPage, recentlyClosedPage, recentlyClosedTab, recordOpen, resolveBack, type OriginDeps } from './menu-page-origin';

export const menuPageState = $state<{ open: string | null; surface: boolean }>({ open: null, surface: false });

let settled: string | null = null;

let returningTo: { id: string; at: number } | null = null;

let pushedFor: string | null = null;

const parked = new Set<string>();
const PARKABLE = 'settings';

function setParked(doc: Document, id: string, on: boolean): void {
    const container = doc.getElementById(menuPage(id)?.containerId ?? '');
    if (on) parked.add(id);
    else parked.delete(id);
    if (!container) return;
    container.toggleAttribute('data-menu-parked', on);
    container.toggleAttribute('inert', on);
}

export function activeMenuPages(doc: Document = document): MenuPage[] {
    return openMenuPages(doc).filter((page) => !parked.has(page.id));
}

export interface ShellDeps {
    selectTab: (tab: string) => void;
    web: () => Record<string, unknown> | null;
    origin?: OriginDeps;
    openDrawer?: () => void;
    hashEnv?: HashEnv;
    confirm?: ConfirmFn | null;
    surface?: SurfaceTracker | null;
}

type Sidebar = { isOpen?: boolean; open?: () => void };
const sidebar = (): Sidebar | undefined => (globalThis as { SessionSidebar?: Sidebar }).SessionSidebar;

const defaultOrigin: OriginDeps = {
    drawerTab: () => (sidebar()?.isOpen === true ? sidebarTabs.active() : recentlyClosedTab()),
    generation: () =>
        (globalThis as { NavigationGeneration?: { current?: () => number } }).NavigationGeneration?.current?.() ?? 0,
};

const defaultDeps: ShellDeps = {
    selectTab: (tab) => {
        sidebarTabs.select(tab);
    },
    web: () => ((globalThis as { CloudeWeb?: Record<string, unknown> }).CloudeWeb ?? null),
};

export function openMenuPages(doc: Document = document): MenuPage[] {
    if (typeof doc.getElementById !== 'function') return [];
    return MENU_PAGES.filter((page) => doc.getElementById(page.containerId)?.firstElementChild);
}

export function closeMenuPagesExcept(
    except: string | null,
    doc: Document = document,
    deps: ShellDeps = defaultDeps,
): string[] {
    const ns = deps.web();
    const closed: string[] = [];
    for (const page of openMenuPages(doc)) {
        if (page.id === except) {
            if (parked.has(page.id)) setParked(doc, page.id, false);
            continue;
        }
        if (except !== null && page.id === PARKABLE && menuPageState.surface && !parked.has(page.id)) {
            setParked(doc, page.id, true);
            continue;
        }
        if (parked.has(page.id)) setParked(doc, page.id, false);
        const closer = ns?.[page.closer];
        if (typeof closer === 'function') {
            (closer as () => unknown)();
            closed.push(page.id);
        }
    }
    return closed;
}

export function pickDrawerTab(
    tab: string,
    doc: Document = document,
    deps: ShellDeps = defaultDeps,
): void {
    if (tab === 'agents') closeMenuPagesExcept(null, doc, deps);
    deps.selectTab(tab);
}

export function backFromMenuPage(doc: Document = document, deps: ShellDeps = defaultDeps): void {
    const page = activeMenuPages(doc).map((p) => p.id).pop() ?? null;
    const from = page ? resolveBack(page, deps.origin ?? defaultOrigin) : ({ kind: 'none' } as const);
    if (from.kind === 'page') {
        const opener = deps.web()?.[(menuPage(from.id)?.closer ?? '').replace(/^close/, 'open')];
        if (typeof opener === 'function') {
            returningTo = { id: from.id, at: performance.now() };
            closeMenuPagesExcept(from.id, doc, deps);
            (opener as () => unknown)();
            return;
        }
    }
    const env = deps.hashEnv ?? (typeof window === 'undefined' ? null : window);
    if (page && pushedFor === page && env && hashNamesPage(env.location.hash, menuPage(page)!) && typeof env.history.back === 'function') {
        pushedFor = null;
        env.history.back();
    } else closeMenuPagesExcept(null, doc, deps);
    if (from.kind === 'drawer') {
        (deps.openDrawer ?? (() => sidebar()?.open?.()))();
        deps.selectTab(from.tab);
    }
}

let popsPending = false;

let confirming = false;

export async function closeMenuPageGuarded(doc: Document = document, deps: ShellDeps = defaultDeps, all = false): Promise<boolean> {
    if (confirming) return false;
    const page = activeMenuPages(doc).map((p) => p.id).pop() ?? null;
    confirming = true;
    try {
        const may = await mayClosePage(page, deps.confirm);
        if (!may || activeMenuPages(doc).map((p) => p.id).pop() !== page) return false;
    } finally {
        confirming = false;
    }
    if (all) {
        closeMenuPagesExcept(null, doc, deps);
        pushedFor = null;
        popsPending = popPageEntries(deps.hashEnv);
    } else backFromMenuPage(doc, deps);
    return true;
}

export function closeMenuPageFromX(doc: Document = document, deps: ShellDeps = defaultDeps): Promise<boolean> {
    return closeMenuPageGuarded(doc, deps, parked.size === 0);
}

export function syncMenuPages(doc: Document = document, deps: ShellDeps = defaultDeps): string | null {
    for (const id of [...parked]) if (!openMenuPages(doc).some((p) => p.id === id)) setParked(doc, id, false);
    if (!activeMenuPages(doc).length && parked.size) setParked(doc, [...parked].pop()!, false);
    const open = activeMenuPages(doc).map((page) => page.id);
    const fresh = open.filter((id) => id !== settled);
    const current: string | null = fresh.length ? (fresh[fresh.length - 1] ?? null) : open.includes(settled ?? '') ? settled : null;
    if (current && open.length > 1) {
        const container = doc.getElementById(menuPage(current)?.containerId ?? '');
        const focused = doc.activeElement;
        const hadFocus = !!(container && focused && container.contains(focused));
        closeMenuPagesExcept(current, doc, deps);
        if (hadFocus && focused instanceof HTMLElement && !container?.contains(doc.activeElement)) focused.focus();
    }
    const body = doc.body;
    if (body) {
        body.classList.toggle(MENU_PAGE_OPEN_CLASS, current !== null);
        if (current) body.dataset.menuPage = current;
        else delete body.dataset.menuPage;
        const surface = deps.surface === undefined ? surfaceTrackerFor(doc) : deps.surface;
        if (current) menuPageState.surface = surface?.start() ?? false;
        else {
            surface?.stop();
            menuPageState.surface = false;
        }
    }
    if (current && current !== settled) {
        if (returningTo && returningTo.id === current && performance.now() - returningTo.at < 1000) returningTo = null;
        else recordOpen(current, settled ?? recentlyClosedPage(), deps.origin ?? defaultOrigin);
        pushedFor = pushPageHash(menuPage(current)!, deps.hashEnv) ? current : null;
        if (!menuPage(current)?.keepDrawerTab) deps.selectTab('menu');
    } else if (!current && settled) {
        noteClosedPage(settled);
        pushedFor = null;
        const gone = menuPage(settled);
        if (gone) queueMicrotask(() => { if (!openMenuPages(doc).length) clearPageHash(gone, deps.hashEnv); });
    }
    settled = current;
    menuPageState.open = current;
    return current;
}

export function reconcilePageWithHash(
    doc: Document = document,
    deps: ShellDeps = defaultDeps,
    hash: string | null = typeof location === 'undefined' ? null : location.hash,
): void {
    const named = pageOfHash(hash);
    const open = openMenuPages(doc);
    if (!named) {
        if (open.length) closeMenuPagesExcept(null, doc, deps);
        return;
    }
    if (open.some((p) => p.id === named.id)) return;
    const opener = deps.web()?.[named.closer.replace(/^close/, 'open')];
    if (typeof opener === 'function') (opener as () => unknown)();
}

function escapeListener(doc: Document, deps: ShellDeps): () => void {
    return initMenuPageEscape(doc, {
        pageOpen: () => openMenuPages(doc).length > 0,
        close: () => void (menuPageState.surface ? closeMenuPageFromX(doc, deps) : closeMenuPageGuarded(doc, deps)),
    });
}

export function initMenuPageShell(doc: Document = document, deps: ShellDeps = defaultDeps): () => void {
    if (typeof MutationObserver !== 'function') {
        syncMenuPages(doc, deps);
        return () => {};
    }
    const observer = new MutationObserver((records) => {
        slideBack(records.flatMap((r) => [...r.removedNodes].filter((n): n is HTMLElement => n instanceof HTMLElement)), doc);
        syncMenuPages(doc, deps);
    });
    for (const page of MENU_PAGES) {
        const container = doc.getElementById(page.containerId);
        if (container) observer.observe(container, { childList: true });
    }
    syncMenuPages(doc, deps);
    const win = doc.defaultView;
    const onTraverse = (): void => {
        if (popsPending) {
            popsPending = false;
            const landed = pageOfHash(win?.location.hash ?? null);
            if (landed) clearPageHash(landed, deps.hashEnv);
        }
        reconcilePageWithHash(doc, deps, win?.location.hash ?? null);
    };
    win?.addEventListener('hashchange', onTraverse);
    win?.addEventListener('popstate', onTraverse);
    const stopEscape = escapeListener(doc, deps);
    const stopOutside = initMenuPageOutside(doc, {
        slideOutOpen: () => menuPageState.surface && openMenuPages(doc).length > 0,
        close: () => void closeMenuPageGuarded(doc, deps, true),
    });
    return () => {
        stopEscape();
        stopOutside();
        observer.disconnect();
        win?.removeEventListener('hashchange', onTraverse);
        win?.removeEventListener('popstate', onTraverse);
    };
}

export function resetMenuPageShell(): void {
    settled = null;
    parked.clear();
    popsPending = false;
    menuPageState.open = null;
    menuPageState.surface = false;
}
