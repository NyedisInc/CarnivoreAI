import type { DynamicTabDef } from '../dynamic-tabs/types';
import { i18n, t } from '../i18n/index.svelte';
import { toCplugItem, type CplugItem, type CplugRow } from '../plugins-page/cplugs-adapter';
import type { Surface } from './api';
import { isPopoutEnabled, titleKeyOf, word } from './panel-views.svelte';
import PluginTabBody from './PluginTabBody.svelte';

export const PLUGIN_TAB_PREFIX = 'cplug-';
const CORE_RAIL_ICONS: ReadonlySet<string> = new Set(['menu', 'agents', 'questions']);
const STRING_OWNER = 'panelviews';

export interface PluginTabEntry {
    readonly tabId: string;
    readonly key: string;
    readonly kind: 'page' | 'sidebar_tab';
    readonly plugin: CplugItem;
    readonly title: string;
    readonly titleKey: string;
    readonly icon: string;
    readonly popout: boolean;
    readonly popoutMulti: boolean;
    readonly surface?: Surface | 'widget' | 'tab';
    readonly view?: string;
    readonly menu?: string;
    readonly main?: string;
}

export const pluginTabs = $state<{ list: PluginTabEntry[]; loaded: boolean }>({ list: [], loaded: false });

function pickIcon(icon: string | null | undefined, fallbackIcon?: string): string {
    const raw = typeof icon === 'string' && icon.trim() ? icon.trim() : '';
    if (raw && !CORE_RAIL_ICONS.has(raw)) return raw;
    return fallbackIcon && !CORE_RAIL_ICONS.has(fallbackIcon) ? fallbackIcon : 'plug';
}

function registerTabTitleKey(tabId: string, title: string): string {
    const titleKey = titleKeyOf(`${tabId}.tab`, title);
    try {
        i18n.extendCatalog?.(STRING_OWNER, { [titleKey]: title });
    } catch {
    }
    return titleKey;
}

export function pluginTabEntries(rows: readonly CplugRow[]): PluginTabEntry[] {
    const out: PluginTabEntry[] = [];
    const seen = new Set<string>();
    for (const row of rows) {
        const isSidecar = row.runtime === 'sidecar';
        const hasCompiledTab = row.runtime === 'compiled' && Boolean(row.sidebar_tab || row.page);
        if ((!isSidecar && !hasCompiledTab) || !row.enabled || row.state !== 'active') continue;
        const plugin = toCplugItem(row, t);
        const uiPopout = isPopoutEnabled(row.popout);
        const baseId = `${PLUGIN_TAB_PREFIX}${word(row.id)}`;

        let hasPage = false;
        const page = row.page;
        if (page) {
            const panels = new Set((row.views ?? []).filter((v) => v.surfaces.includes('panel')).map((v) => v.name));
            if (panels.has(page.menu) && panels.has(page.main) && !seen.has(baseId)) {
                seen.add(baseId);
                hasPage = true;
                const mark = t(plugin.unverified ? 'cplug_ui.mark.unverified' : 'cplug_ui.mark.third_party');
                const title = t('cplug_ui.page.title', { mark, name: plugin.name });
                const titleKey = registerTabTitleKey(baseId, title);
                const pagePopout = isPopoutEnabled(page.popout) ?? uiPopout ?? false;
                const multi = typeof page.popout === 'object' && page.popout !== null && page.popout.multi === true;
                out.push({
                    tabId: baseId,
                    key: `${row.id}:${row.install_key ?? ''}:page`,
                    kind: 'page',
                    plugin,
                    title,
                    titleKey,
                    icon: pickIcon(plugin.icon, 'plug'),
                    popout: pagePopout,
                    popoutMulti: multi,
                    menu: page.menu,
                    main: page.main,
                });
            }
        }

        const st = row.sidebar_tab;
        if (st && typeof st === 'object') {
            const explicitId = typeof st.id === 'string' && st.id.trim() ? word(st.id.trim()) : '';
            const tabId = hasPage || explicitId ? `${baseId}-${explicitId || 'tab'}` : baseId;
            if (seen.has(tabId)) continue;
            seen.add(tabId);
            const title = typeof st.title === 'string' && st.title.trim() ? st.title.trim() : plugin.name;
            const titleKey = registerTabTitleKey(tabId, title);
            const popout = isPopoutEnabled(st.popout) ?? uiPopout ?? false;
            const multi =
                st.popout_multi === true ||
                st.multi === true ||
                (typeof st.popout === 'object' && st.popout !== null && st.popout.multi === true);
            const view = typeof st.view === 'string' && st.view.trim() ? st.view.trim() : undefined;
            out.push({
                tabId,
                key: `${row.id}:${row.install_key ?? ''}:sidebar_tab`,
                kind: 'sidebar_tab',
                plugin,
                title,
                titleKey,
                icon: pickIcon(st.icon ?? undefined, plugin.icon),
                popout,
                popoutMulti: multi,
                surface: 'tab',
                ...(view ? { view } : {}),
            });
        }
    }
    return out;
}

export function setPluginTabs(rows: readonly CplugRow[]): void {
    pluginTabs.list = pluginTabEntries(rows);
    pluginTabs.loaded = true;
}

export function pluginTabOf(tabId: string): PluginTabEntry | undefined {
    return pluginTabs.list.find((entry) => entry.tabId === tabId);
}

export function runtimePopoutTabDefs(): DynamicTabDef[] {
    return pluginTabs.list
        .filter((entry) => entry.popout)
        .map((entry, idx) => ({
            id: entry.tabId,
            labelKey: entry.titleKey,
            nameKey: entry.titleKey,
            icon: entry.icon,
            order: 900 + idx,
            persist: false,
            focusOnAppear: false,
            widgetArea: 'closed' as const,
            popout: true,
            popoutMulti: entry.popoutMulti,
            present: () => pluginTabOf(entry.tabId)?.popout === true,
            body: { component: PluginTabBody, titleKey: entry.titleKey },
        }));
}
