import { MENU_PAGES, type MenuPage } from './menu-pages';

export interface HashEnv {
    location: Pick<Location, 'hash' | 'pathname' | 'search'>;
    history: Pick<History, 'pushState' | 'replaceState' | 'state' | 'back'>;
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

export function pushPageHash(page: MenuPage, env: HashEnv | null = liveEnv()): boolean {
    if (!env || hashNamesPage(env.location.hash, page)) return false;
    try {
        env.history.pushState(env.history.state, '', `${env.location.pathname}${env.location.search}${page.hashes[0]}`);
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
