import { RAIL_HINT_ROWS } from '../../opscenter/shell/rail-hints';
import { CATALOG_KEY_ROWS } from '../catalog/keys';
import { SEARCH_BINDINGS } from '../terminal-search/search-keys';
import { SETTINGS_KEY_ROWS } from '../settings-page/settings-shortcut';
import { ZOOM_KEY_ROWS } from '../../opscenter/engine/layout-zoom.svelte';

export interface KeyRow {
    keys: string;
    labelKey: string;
}

export interface KeySection {
    id: 'menu' | 'terminal-search' | 'terminal-zoom' | 'catalog' | 'settings';
    titleKey: string;
    rows: KeyRow[];
}

export function keySections(): KeySection[] {
    const sections: KeySection[] = [
        {
            id: 'menu',
            titleKey: 'keys.page.section.menu',
            rows: RAIL_HINT_ROWS.map((r) => ({ keys: r.keys, labelKey: r.labelKey })),
        },
        {
            id: 'terminal-search',
            titleKey: 'keys.page.section.terminal_search',
            rows: SEARCH_BINDINGS.map((b) => ({ keys: b.keys, labelKey: b.labelKey })),
        },
        {
            id: 'terminal-zoom',
            titleKey: 'keys.page.section.terminal_zoom',
            rows: ZOOM_KEY_ROWS.map((r) => ({ keys: r.keys, labelKey: r.labelKey })),
        },
        {
            id: 'catalog',
            titleKey: 'keys.page.section.catalog',
            rows: CATALOG_KEY_ROWS.map(([keys, labelKey]) => ({ keys, labelKey })),
        },
        {
            id: 'settings',
            titleKey: 'keys.page.section.settings',
            rows: SETTINGS_KEY_ROWS.map((r) => ({ ...r })),
        },
    ];
    return sections.filter((s) => s.rows.length > 0);
}
