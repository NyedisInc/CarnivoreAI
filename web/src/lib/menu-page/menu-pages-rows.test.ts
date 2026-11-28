/** @vitest-environment jsdom */
import { describe, expect, test } from 'vitest';
import { MENU_PAGES, type MenuPage } from './menu-pages';
import { RAIL_DESTINATIONS, RAIL_HELP_LINKS, WARROOM_ROW, type RailItem } from '../../opscenter/shell/rail-items';

const DRAWER_ROWS: readonly RailItem[] = [...RAIL_DESTINATIONS, WARROOM_ROW, ...RAIL_HELP_LINKS];

function untied(rows: readonly Pick<RailItem, 'id' | 'run'>[], pages: readonly Pick<MenuPage, 'railItem'>[]): string[] {
    return rows.filter((r) => r.run && !pages.some((p) => p.railItem === r.id)).map((r) => r.id);
}

describe('drawer rows and menu pages', () => {
    test('the scan sees the rows (a check that looked at nothing proves nothing)', () => {
        expect(DRAWER_ROWS.length).toBeGreaterThanOrEqual(12);
        expect(DRAWER_ROWS.filter((r) => r.run).length).toBeGreaterThanOrEqual(12);
    });

    test('every drawer row with an action is the railItem of a menu page, so it can wear the frame check and light up', () => {
        expect(untied(DRAWER_ROWS, MENU_PAGES)).toEqual([]);
    });

    test('negative control: a planted row, and a page with no railItem, go red', () => {
        expect(untied([{ id: 'plugin-link', run: () => {} }], MENU_PAGES)).toEqual(['plugin-link']);
        expect(untied([{ id: 'inert' }], MENU_PAGES)).toEqual([]);
        expect(untied(DRAWER_ROWS, MENU_PAGES.map((p) => (p.id === 'widgets' ? { railItem: null } : p)))).toEqual(['widgets']);
    });
});
