import { expect, test } from 'vitest';
import { keySections } from './key-bindings';
import { RAIL_HINT_ROWS, railHint } from '../../opscenter/shell/rail-hints';
import { RAIL_DESTINATIONS, RAIL_HELP_LINKS, WARROOM_ROW } from '../../opscenter/shell/rail-items';
import { SEARCH_BINDINGS, route } from '../terminal-search/search-keys';
import { CATALOG_KEY_ROWS, keyAction } from '../catalog/keys';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';

test('every search row does what it says when its chord is routed', () => {
    for (const b of SEARCH_BINDINGS) {
        expect(route(b.sample, b.ctx).action, b.keys).toBe(b.action);
    }
});

test('every catalog row names a key keyAction answers', () => {
    for (const [keys] of CATALOG_KEY_ROWS) {
        const pressed = keys === 'j  k' ? ['j', 'k'] : [keys === 'enter' ? 'Enter' : keys];
        for (const key of pressed) expect(keyAction({ key }, false), key).not.toBeNull();
    }
});

test('the sections are the five live groups', () => {
    expect(keySections().map((s) => s.id)).toEqual(['menu', 'terminal-search', 'terminal-zoom', 'catalog', 'settings']);
});

test('every catalog key the page reaches for exists', () => {
    const cat = enCatalog as Record<string, string>;
    for (const s of keySections()) {
        expect(cat[s.titleKey], s.titleKey).toBeTruthy();
        for (const r of s.rows) if (r.labelKey) expect(cat[r.labelKey], r.labelKey).toBeTruthy();
    }
    for (const view of ['docs', 'keys', 'changelog']) {
        expect(cat[`info.page.${view}.title`]).toBeTruthy();
        expect(cat[`info.page.${view}.label`]).toBeTruthy();
    }
});

test('the menu group is the list that draws the row hints, and every row agrees', () => {
    const menu = keySections().find((s) => s.id === 'menu');
    expect(menu?.rows.map((r) => r.keys)).toEqual(RAIL_HINT_ROWS.map((r) => r.keys));
    const rows = [...RAIL_DESTINATIONS, WARROOM_ROW, ...RAIL_HELP_LINKS];
    for (const row of rows) expect(row.hint, row.id).toBe(railHint(row.id));
    const KEY_ONLY = ['wrappers', 'home'];
    for (const h of RAIL_HINT_ROWS.filter((r) => !KEY_ONLY.includes(r.id))) {
        expect(rows.find((r) => r.id === h.id)?.labelKey, h.id).toBe(h.labelKey);
    }
});
