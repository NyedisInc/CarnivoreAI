import { panelInstance, unmountPanel } from '../mount';
import { whenLegacyBootComplete } from '../legacy-boot';
import { skillsNode, type OldSkillsTab } from '../skills-hub/tabs';
import { WAREZ_HASH, closeWarezScreen, isWarezHash, openWarezScreen } from './warez-host';
import { RESERVED_SEGMENTS, parseNodeHash } from './menu/route';

export const CATALOG_SCREEN_CONTAINER = 'catalog-screen';

export const CATALOG_HASH = '#catalog';

export const SKILLS_HASH = '#skills';

export const SKILLS_MANAGER_HASH = '#skills-manager';

export interface CatalogOpenOptions {
    kind?: string;
    item?: string;
    tab?: OldSkillsTab | 'stats';
}

interface ScreenHandle {
    show?: (options?: CatalogOpenOptions) => void;
    close?: () => void;
    isOpen?: () => boolean;
}

export function unmountCatalogScreen(): boolean {
    return unmountPanel(CATALOG_SCREEN_CONTAINER);
}

export function openCatalogScreen(options: CatalogOpenOptions = {}): boolean {
    if (options.tab) return openWarezScreen({ node: skillsNode(options.tab) });
    return openWarezScreen({
        ...(options.kind ? { kind: options.kind } : {}),
        ...(options.item ? { item: options.item } : {}),
    });
}

export function closeCatalogScreen(): boolean {
    const handle = panelInstance(CATALOG_SCREEN_CONTAINER) as ScreenHandle | null;
    if (!handle || typeof handle.close !== 'function') return false;
    handle.close();
    return true;
}

export function isSkillsHash(hash: string | null | undefined): boolean {
    if (typeof hash !== 'string') return false;
    const trimmed = hash.trim();
    if (!trimmed) return false;
    const bare = trimmed.startsWith('#') ? trimmed.slice(1) : trimmed;
    return bare === SKILLS_HASH.slice(1) || bare === SKILLS_MANAGER_HASH.slice(1);
}

export function catalogHashItem(hash: string | null | undefined): string | null {
    if (typeof hash !== 'string') return null;
    const bare = hash.trim().replace(/^#/, '');
    const prefix = [CATALOG_HASH, WAREZ_HASH].map((h) => `${h.slice(1)}/`).find((p) => bare.startsWith(p));
    if (!prefix) return null;
    const rest = bare.slice(prefix.length);
    if (RESERVED_SEGMENTS.includes(rest.split('/')[0] ?? '')) return null;
    try {
        const id = decodeURIComponent(rest).trim();
        return id ? id.slice(0, 200) : null;
    } catch {
        return null;
    }
}

export function wireCatalogDeepLink(
    target: Window | null = typeof window !== 'undefined' ? window : null,
): () => void {
    if (!target) return () => {};
    const apply = (): void => {
        const hash = target.location?.hash;
        if (isWarezHash(hash)) {
            const item = catalogHashItem(hash);
            const node = parseNodeHash(hash);
            openWarezScreen(item ? { item } : node ? { node } : { home: true });
        } else if (isSkillsHash(hash)) {
            openWarezScreen({ node: skillsNode() });
        } else {
            closeCatalogScreen();
            closeWarezScreen();
        }
    };
    target.addEventListener('hashchange', apply);
    const stopWaiting = whenLegacyBootComplete(target, apply);
    return () => {
        stopWaiting();
        target.removeEventListener('hashchange', apply);
    };
}
