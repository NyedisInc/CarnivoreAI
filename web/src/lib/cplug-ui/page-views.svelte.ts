import type { Component } from 'svelte';
import { registerTab, tabRegistry } from '../dynamic-tabs/registry';
import type { DynamicTabDef } from '../dynamic-tabs/types';
import { i18n, t } from '../i18n/index.svelte';
import { toCplugItem, type CplugItem, type CplugRow } from '../plugins-page/cplugs-adapter';
import { registerTabFlyouts } from '../sidebar-widgets/tab-flyouts';
import PageMain from './PageMain.svelte';
import PageMenu from './PageMenu.svelte';
import PageSwitch from './PageSwitch.svelte';
import { titleKeyOf, word } from './panel-views.svelte';

export const PAGE_TAB_PREFIX = 'cplug-';
export const PAGE_ORDER_FROM = 900;
export const PAGE_ORDER_TO = 999;
const CORE_RAIL_ICONS: ReadonlySet<string> = new Set(['menu', 'agents', 'questions']);
const STRING_OWNER = 'panelviews';

export type PageStep = 'menu' | 'view';

export interface PageEntry {
    readonly tabId: string;
    readonly key: string;
    readonly plugin: CplugItem;
    readonly menu: string;
    readonly main: string;
    readonly title: string;
    readonly icon: string;
}

export const pages = $state<{ list: PageEntry[] }>({ list: [] });
export const pageSteps = $state<Record<string, PageStep>>({});

/* }, views: [{ name: */
export function pageEntries(rows: readonly CplugRow[]): PageEntry[] {
    const out: PageEntry[] = [];
    for (const row of rows) {
        const page = row.page;
        if (row.runtime !== 'sidecar' || !row.enabled || row.state !== 'active' || !page) continue;
        const panels = new Set((row.views ?? []).filter((view) => view.surfaces.includes('panel')).map((view) => view.name));
        if (!panels.has(page.menu) || !panels.has(page.main)) continue;
        const plugin = toCplugItem(row, t);
        const mark = t(plugin.unverified ? 'cplug_ui.mark.unverified' : 'cplug_ui.mark.third_party');
        out.push({
            tabId: `${PAGE_TAB_PREFIX}${word(row.id)}`,
            key: `${row.id}:${row.install_key ?? ''}`,
            plugin,
            menu: page.menu,
            main: page.main,
            title: t('cplug_ui.page.title', { mark, name: plugin.name }),
            icon: !plugin.icon || CORE_RAIL_ICONS.has(plugin.icon) ? 'plug' : plugin.icon,
        });
    }
    return out;
}

export function pageOf(tabId: string): PageEntry | undefined {
    return pages.list.find((entry) => entry.tabId === tabId);
}

function nextOrder(): number | null {
    const taken = new Set(tabRegistry.all().map((def) => def.order));
    for (let order = PAGE_ORDER_FROM; order <= PAGE_ORDER_TO; order++) if (!taken.has(order)) return order;
    return null;
}

function tabDefOf(entry: PageEntry, order: number): DynamicTabDef {
    const titleKey = titleKeyOf(`${entry.tabId}.page`, entry.title);
    i18n.extendCatalog?.(STRING_OWNER, { [titleKey]: entry.title });
    return {
        id: entry.tabId,
        labelKey: titleKey,
        nameKey: titleKey,
        icon: entry.icon,
        order,
        persist: false,
        focusOnAppear: false,
        widgetArea: 'closed',
        present: () => pageOf(entry.tabId) !== undefined,
        mainView: PageMain,
        mainViewOnPhone: false,
        body: { component: PageMenu, titleKey, titleActions: PageSwitch as unknown as Component<{ popout?: boolean }> },
    };
}

export function setPages(rows: readonly CplugRow[]): void {
    const list = pageEntries(rows);
    let added = false;
    for (const entry of list) {
        if (tabRegistry.get(entry.tabId)) continue;
        const order = nextOrder();
        if (order === null || registerTab(tabDefOf(entry, order)) !== null) continue;
        added = true;
    }
    pages.list = list;
    if (added) registerTabFlyouts();
}

export function showStep(tabId: string, step: PageStep): void {
    pageSteps[tabId] = step;
}
