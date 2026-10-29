
export const SURFACE_MIN_WIDTH_PX = 1024;

export const MENU_PAGE_SURFACE_CLASS = 'menu-page-surface';

export const SURFACE_INSET_VARS = [
    '--menu-surface-top',
    '--menu-surface-left',
    '--menu-surface-right',
    '--menu-surface-bottom',
] as const;

export const SURFACE_SELECTORS = ['#terminal-grid > .oc-surface', '#launchpad-screen .oc-surface'] as const;

/* the bottom bar */
const COVERED_SELECTOR = [...SURFACE_SELECTORS, '#browser-screen'].join(', ');

export interface SurfaceInsets {
    top: number;
    left: number;
    right: number;
    bottom: number;
}

export interface SurfaceEnv {
    doc: Document;
    win: Window & typeof globalThis;
}

export function findSurface(doc: Document, win: Pick<Window, 'innerWidth'>): HTMLElement | null {
    if (win.innerWidth < SURFACE_MIN_WIDTH_PX) return null;
    for (const selector of SURFACE_SELECTORS) {
        const el = doc.querySelector<HTMLElement>(selector);
        const box = el?.getBoundingClientRect();
        if (el && box && box.width > 0 && box.height > 0) return el;
    }
    return null;
}

export function insetsOf(el: HTMLElement, win: Pick<Window, 'innerWidth' | 'innerHeight'>): SurfaceInsets {
    const box = el.getBoundingClientRect();
    const round = (n: number): number => Math.round(Math.max(0, n) * 100) / 100;
    return {
        top: round(box.top),
        left: round(box.left),
        right: round(win.innerWidth - box.right),
        bottom: round(win.innerHeight - box.bottom),
    };
}

export interface SurfaceTracker {
    start(): boolean;
    stop(): void;
    refresh(): boolean;
}

export function createSurfaceTracker(env: SurfaceEnv): SurfaceTracker {
    const { doc, win } = env;
    let observer: ResizeObserver | null = null;
    let mutations: MutationObserver | null = null;
    let watched: Element | null = null;
    let running = false;

    const covered = new Set<HTMLElement>();

    const setCovered = (on: boolean): void => {
        const now = on ? [...doc.querySelectorAll<HTMLElement>(COVERED_SELECTOR)] : [];
        for (const el of [...covered]) {
            if (now.includes(el)) continue;
            el.removeAttribute('inert');
            covered.delete(el);
        }
        for (const el of now) {
            el.setAttribute('inert', '');
            covered.add(el);
        }
    };

    const clear = (): void => {
        for (const name of SURFACE_INSET_VARS) doc.documentElement.style.removeProperty(name);
        doc.body?.classList.remove(MENU_PAGE_SURFACE_CLASS);
        setCovered(false);
    };

    const watch = (surface: HTMLElement | null): void => {
        if (surface === watched || typeof win.ResizeObserver !== 'function') return;
        observer?.disconnect();
        watched = surface;
        if (!surface) return;
        const next = observer ?? new win.ResizeObserver(() => refresh());
        observer = next;
        for (const el of [surface, surface.parentElement, doc.body, doc.getElementById('layout-command-bar')]) if (el) next.observe(el);
    };

    function refresh(): boolean {
        const surface = running ? findSurface(doc, win) : null;
        if (!surface) {
            clear();
            watch(null);
            return false;
        }
        const insets = insetsOf(surface, win);
        const bar = doc.getElementById('layout-command-bar')?.getBoundingClientRect();
        if (bar && bar.height > 0 && bar.top < insets.top) insets.top = Math.max(0, Math.round(bar.top * 100) / 100);
        const style = doc.documentElement.style;
        style.setProperty('--menu-surface-top', `${insets.top}px`);
        style.setProperty('--menu-surface-left', `${insets.left}px`);
        style.setProperty('--menu-surface-right', `${insets.right}px`);
        style.setProperty('--menu-surface-bottom', `${insets.bottom}px`);
        doc.body?.classList.add(MENU_PAGE_SURFACE_CLASS);
        setCovered(true);
        watch(surface);
        return true;
    }

    const onWindow = (): void => {
        refresh();
    };

    return {
        start(): boolean {
            if (!running) {
                running = true;
                win.addEventListener('resize', onWindow);
                const grid = doc.getElementById('terminal-grid');
                if (grid && typeof win.MutationObserver === 'function') {
                    const seen = new win.MutationObserver(onWindow);
                    seen.observe(grid, { childList: true });
                    mutations = seen;
                }
            }
            return refresh();
        },
        stop(): void {
            if (!running) return;
            running = false;
            win.removeEventListener('resize', onWindow);
            mutations?.disconnect();
            mutations = null;
            observer?.disconnect();
            observer = null;
            watched = null;
            clear();
        },
        refresh,
    };
}

const trackers = new WeakMap<Document, SurfaceTracker>();

export function surfaceTrackerFor(doc: Document): SurfaceTracker | null {
    const win = doc.defaultView;
    if (!win) return null;
    let tracker = trackers.get(doc);
    if (!tracker) {
        tracker = createSurfaceTracker({ doc, win });
        trackers.set(doc, tracker);
    }
    return tracker;
}
