import { SETTINGS_SECTIONS, type SectionId } from './settings-registry';
import { hashNamesPage, type HashEnv } from '../menu-page/menu-page-hash';
import { menuPage } from '../menu-page/menu-pages';

const HASH = /^#?settings\/([a-z_]+)(?:\/([a-z_]+))?$/;

const PLUGIN_HASH = /^#?settings\/plugin\/([a-z0-9_.-]+)$/;

const HIGHLIGHT = /\?highlight=([a-z0-9_.-]+)$/;

const withoutHighlight = (hash: string): string => hash.trim().replace(HIGHLIGHT, '');

const MOVED = /^#?(wrappers|launch-profiles|shortcuts)(?:\/([a-z_]+))?$/;
const MOVED_SECTION: Record<string, SectionId> = { wrappers: 'launch_profiles', 'launch-profiles': 'launch_profiles', shortcuts: 'keys' };

export function settingsSectionOf(hash: string | null | undefined): SectionId | null {
    return settingsTabOf(hash)?.section ?? null;
}

export function settingsTabOf(hash: string | null | undefined): { section: SectionId; tab: string | null } | null {
    if (typeof hash !== 'string') return null;
    const bare = withoutHighlight(hash);
    const moved = MOVED.exec(bare);
    const movedSection = moved?.[1] === undefined ? undefined : MOVED_SECTION[moved[1]];
    if (moved && movedSection) return { section: movedSection, tab: moved[2] ?? null };
    const match = HASH.exec(bare);
    const section = SETTINGS_SECTIONS.find((s) => s.id === match?.[1])?.id;
    return section ? { section, tab: match?.[2] ?? null } : null;
}

export function settingsHighlightOf(hash: string | null | undefined): string | null {
    if (!settingsTabOf(hash)) return null;
    return HIGHLIGHT.exec(String(hash).trim())?.[1] ?? null;
}

export function settingsHashWithoutHighlight(hash: string): string {
    return withoutHighlight(hash);
}

export function settingsFragment(section: SectionId, tab?: string | null): string {
    return `#settings/${section}${tab ? `/${tab}` : ''}`;
}

export function writeSettingsFragment(
    fragment: string,
    mode: 'push' | 'replace' | 'auto' = 'auto',
    env: HashEnv | null = typeof window === 'undefined' ? null : window,
): void {
    const page = menuPage('settings');
    if (!env || !page) return;
    const target = `${env.location.pathname}${env.location.search}${fragment.startsWith('#') ? fragment : `#${fragment}`}`;
    if (target === `${env.location.pathname}${env.location.search}${env.location.hash}`) return;
    const push = mode === 'push' || (mode === 'auto' && !hashNamesPage(env.location.hash, page));
    try {
        if (push) env.history.pushState(env.history.state, '', target);
        else env.history.replaceState(env.history.state, '', target);
    } catch (error) {
        console.debug('settings hash not written', error);
    }
}

export function settingsPluginOf(hash: string | null | undefined): string | null {
    if (typeof hash !== 'string') return null;
    return PLUGIN_HASH.exec(withoutHighlight(hash))?.[1] ?? null;
}

export function settingsPluginFragment(cplugId: string): string {
    return `#settings/plugin/${cplugId}`;
}
