import { MENU_PAGES, type MenuPage } from './menu-pages';

export interface HashEnv {
    location: Pick<Location, 'hash' | 'pathname' | 'search'>;
    history: Pick<History, 'pushState' | 'replaceState' | 'state' | 'back'> & Partial<Pick<History, 'go'>>;
}

function liveEnv(): HashEnv | null {
    return typeof window === 'undefined' || !window.history ? null : window;
}

export function hashNamesPage(hash: string | null | undefined, page: MenuPage): boolean {
    if (typeof hash !== 'string') return false;
    const bare = hash.trim().replace(/^#/, '');
    return page.hashes.some((h) => {
        const name = h.replace(/^#/, '');
        return bare === name || bare.startsWith(`${name}/`) || bare.startsWith(`${name}?`);
    });
}

export function pageOfHash(hash: string | null | undefined): MenuPage | null {
    return MENU_PAGES.find((page) => hashNamesPage(hash, page)) ?? null;
}

const DEPTH_KEY = 'menuPageDepth';

export function menuPageHistoryDepth(env: HashEnv | null = liveEnv()): number {
    const state: unknown = env?.history.state;
    const depth = state && typeof state === 'object' ? (state as Record<string, unknown>)[DEPTH_KEY] : 0;
    return typeof depth === 'number' && depth > 0 ? depth : 0;
}

export function popPageEntries(env: HashEnv | null = liveEnv()): boolean {
    const depth = menuPageHistoryDepth(env);
    if (!env || !depth || typeof env.history.go !== 'function') return false;
    env.history.go(-depth);
    return true;
}

export function pushPageHash(page: MenuPage, env: HashEnv | null = liveEnv()): boolean {
    if (!env || hashNamesPage(env.location.hash, page)) return false;
    try {
        const prev: unknown = env.history.state;
        const state = prev === null || prev === undefined || typeof prev === 'object'
            ? { ...(prev as object | null), [DEPTH_KEY]: menuPageHistoryDepth(env) + 1 }
            : prev;
        env.history.pushState(state, '', `${env.location.pathname}${env.location.search}${page.hashes[0]}`);
        return true;
    } catch (error) {
        console.debug('menu page hash not written', error);
        return false;
    }
}

export function clearPageHash(page: MenuPage, env: HashEnv | null = liveEnv()): boolean {
    if (!env || !hashNamesPage(env.location.hash, page)) return false;
    try {
        env.history.replaceState(env.history.state, '', `${env.location.pathname}${env.location.search}`);
        return true;
    } catch (error) {
        console.debug('menu page hash not cleared', error);
        return false;
    }
}
