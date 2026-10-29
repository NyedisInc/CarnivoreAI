/* the warez menu */
import { themes } from '../../../opscenter/api';
import { resourcePush } from '../../resource-push/boot';
import type { Translate } from '../../sessions/types';
import { listCplugItems, type CplugItem } from '../../plugins-page/cplugs-adapter';
import { fetchInventory } from '../../skills-page/skills-api';
import { toItems, type ContextChoice, type SkillItem } from '../../skills-page/skills-model';
import type { Inventory } from '../../skills-page/skills-types';
import { data as modsData, follow as followMods } from '../../mods/store.svelte';
import { listedCatalogPlugins } from '../../plugins-page/plugin-listing';
import { newestItems } from '../census';
import { updateCount } from '../filter';
import { isBuiltinPlugin, isBuiltinTheme, isBundledSkill } from '../app-own';
import type { CatalogData } from '../catalog-data.svelte';
import type { FlaggedEntry, InstalledEntry, MenuSources, StoreEntry } from './model';
import { MENU_KINDS, type MenuKind } from './route';
import { countByDisplayKind, displayKind } from '../kind-display';

const POLL_MS = 30_000;
const TOPICS = ['catalog', 'local_skills'] as const;

export const GLOBAL_CONTEXT: ContextChoice = { id: 'global', kind: 'global', label: '', projectPath: null, profile: null };

export interface MenuData {
    readonly sources: MenuSources;
    readonly plugins: readonly CplugItem[] | null;
    readonly skills: readonly SkillItem[] | null;
    readonly inventory: Inventory | null;
    reload(): Promise<void>;
    start(): () => void;
}

function pluginWord(state: string, t: Translate): string {
    const key = { active: 'on', disabled: 'off', needs_approval: 'grant', inert: 'waiting', unavailable: 'held', removed: 'removed' }[state] ?? 'on';
    return t(`warez.menu.word.${key}`);
}

export function createMenuData(catalog: CatalogData, t: Translate): MenuData {
    let plugins = $state<readonly CplugItem[] | null>(null);
    let skills = $state<readonly SkillItem[] | null>(null);
    let inventory = $state<Inventory | null>(null);
    let tick = $state(0);
    let reloads = 0;

    async function reload(): Promise<void> {
        tick = ++reloads;
        const [p, s] = await Promise.allSettled([listCplugItems(t), fetchInventory({ projectPath: null, profile: null })]);
        if (p.status === 'fulfilled') plugins = p.value;
        if (s.status === 'fulfilled') {
            inventory = s.value;
            skills = toItems(s.value, GLOBAL_CONTEXT, t);
        }
    }

    const sources = $derived.by((): MenuSources => {
        const items = catalog.items.filter((item) => !!item?.id);
        const storeByKind = countByDisplayKind(items, MENU_KINDS) as Record<MenuKind, number>;
        const storeItems: StoreEntry[] = items.map((item) => ({
            kind: displayKind(item.kind) as MenuKind,
            id: item.id as string,
            title: (item.card?.title as string | undefined) ?? item.name ?? (item.id as string),
            installed: (catalog.installed[item.id as string] ?? []).length > 0,
        }));
        const themeRows = (themes.status === 'ok' ? (themes.data ?? []) : []).filter((m) => !isBuiltinTheme(m.source));
        void tick;
        const activeTheme = typeof document === 'undefined' ? null : document.documentElement.dataset.theme;
        const verdicts = new Map(catalog.cards.map((card) => [card.id, card.verdict]));
        const fromCatalog = (kind: MenuKind, have: readonly InstalledEntry[]): InstalledEntry[] =>
            items
                .filter((item) => displayKind(item.kind) === kind && (catalog.installed[item.id as string] ?? []).length > 0)
                .filter((item) => !have.some((e) => [e.key, e.title].some((n) => n.toLowerCase() === (item.name ?? '').toLowerCase() || n === item.id)))
                .map((item) => ({
                    key: item.id as string,
                    title: (item.card?.title as string | undefined) ?? item.name ?? (item.id as string),
                    word: kind === 'theme' ? '' : t('warez.menu.word.on'),
                    catalogId: item.id as string,
                }));
        const own: Record<MenuKind, readonly InstalledEntry[]> = {
            skill: (skills ?? []).filter((s) => !isBundledSkill(s.group.locations.map((l) => l.managed?.item_id))).map((s) => ({ key: s.id, title: s.name, word: t(s.off ? 'warez.menu.word.off' : 'warez.menu.word.on') })),
            theme: themeRows.map((m) => ({ key: m.id, title: m.name, word: m.id === activeTheme ? t('warez.menu.word.global') : '' })),
            mod: (modsData.list?.mods ?? []).map((m) => ({ key: m.mod_id, title: m.name ?? m.path, word: t(`warez.menu.word.${m.state === 'partial' ? 'partial' : m.state}`) })),
            plugin: [
                ...(plugins ?? []).filter((p) => !isBuiltinPlugin(p.tier)).map((p) => ({ key: p.cplugId, title: p.name, word: pluginWord(p.state, t) })),
                ...listedCatalogPlugins(items.filter((item) => displayKind(item.kind) === 'plugin'), new Set(Object.keys(catalog.installed).filter((id) => (catalog.installed[id] ?? []).length > 0))).map((item) => ({
                    key: item.id as string,
                    title: (item.card?.title as string | undefined) ?? item.name ?? (item.id as string),
                    word: t((catalog.installed[item.id as string] ?? []).length > 0 ? 'warez.menu.word.on' : 'warez.menu.word.off'),
                    catalogId: item.id as string,
                })),
            ],
        };
        const installed = Object.fromEntries(MENU_KINDS.map((kind) => [kind, kind === 'plugin' ? own[kind] : [...own[kind], ...fromCatalog(kind, own[kind])]])) as unknown as Record<MenuKind, readonly InstalledEntry[]>;
        const flagged: FlaggedEntry[] = MENU_KINDS.flatMap((kind) =>
            installed[kind].filter((e) => e.catalogId && ['flagged', 'blocked'].includes(verdicts.get(e.catalogId) ?? '')).map((e) => ({ ...e, kind })),
        );
        const updates = Object.values(catalog.installed).reduce((n, rows) => n + (updateCount(rows) > 0 ? 1 : 0), 0);
        const consent = (plugins ?? []).filter((p) => !isBuiltinPlugin(p.tier) && p.state === 'needs_approval').length;
        const missing = (modsData.list?.groups ?? []).filter((g) => g.status === 'settings_missing').length;
        return {
            storeTotal: items.length,
            storeNewest: newestItems(items).length,
            storeUpdates: updates,
            storeByKind,
            storeItems,
            installed,
            flagged,
            needs: [
                { page: 'consent', count: consent },
                { page: 'flagged', count: flagged.length },
                { page: 'settings', count: missing },
                { page: 'updates', count: updates },
            ],
        };
    });

    return {
        get sources() { return sources; },
        get plugins() { return plugins; },
        get skills() { return skills; },
        get inventory() { return inventory; },
        reload,
        start(): () => void {
            void reload();
            const stopPush = resourcePush().pushOrPoll(() => void reload(), POLL_MS, TOPICS);
            const stopMods = followMods();
            return () => { stopPush(); stopMods(); };
        },
    };
}
