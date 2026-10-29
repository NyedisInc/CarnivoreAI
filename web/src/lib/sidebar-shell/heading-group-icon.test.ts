/** @vitest-environment jsdom */
import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { iconSvg } from '../../../../client/js/icons/icon-registry.js';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as GroupStore from '../drawer/group-store';
import * as Store from '../drawer/store';

const UUID = 'g-1';
const KEY = `g:${UUID}`;
const ROWS = [{ name: 'cloude_a', created_by_cloude: true, created_at_epoch: 1_700_000_000, status: 'working', unread: false }];

beforeAll(() => { loadLegacyDrawer(); });
beforeEach(() => { resetDrawer(); });

function heading(icon: unknown, collapsed: boolean): string {
    GroupStore.apply({
        status: 'ok',
        groups: [{ group_uuid: UUID, name: 'research', position: 0, members: ['cloude_a'], colour: 'teal', icon } as never],
    });
    Store.save([], ROWS.map((r) => r.name), collapsed ? [KEY] : []);
    const html = drawList(ROWS);
    const start = html.indexOf(`data-group-toggle="${KEY}"`);
    expect(start, 'setup: the group heading is drawn').toBeGreaterThan(-1);
    return html.slice(html.lastIndexOf('<div', start), html.indexOf('</div>', start));
}

function at(html: string, needle: string): number {
    const i = html.indexOf(needle);
    expect(i, `expected ${needle}`).toBeGreaterThan(-1);
    return i;
}

describe('a group heading\'s picked icon', () => {
    it('no icon, a null icon and an unknown id draw no mark and the same heading', () => {
        const none = heading(undefined, false);
        expect(none).not.toContain('data-group-icon');
        expect(heading(null, false)).toBe(none);
        expect(heading('from-the-future', false)).toBe(none);
    });
    it('expanded: chevron, then the icon, then the title; no light', () => {
        const html = heading('flask', false);
        const chevron = at(html, 'session-sidebar-group__chevron');
        const icon = at(html, 'data-group-icon="flask"');
        const label = at(html, 'session-sidebar-group__label');
        expect(chevron < icon && icon < label).toBe(true);
        expect(html).not.toContain('session-sidebar-group__project-led');
        const own = document.createElement('div');
        own.innerHTML = iconSvg('flask', 12);
        expect(html).toContain(own.innerHTML);
        expect(html).toMatch(/data-group-icon="flask" aria-hidden="true"/);
    });
    it('collapsed: chevron, then the light, then the icon, then the title', () => {
        const html = heading('flask', true);
        const chevron = at(html, 'session-sidebar-group__chevron');
        const led = at(html, 'session-sidebar-group__project-led');
        const icon = at(html, 'data-group-icon="flask"');
        const label = at(html, 'session-sidebar-group__label');
        expect(chevron < led && led < icon && icon < label).toBe(true);
    });
    it('the icon strokes currentColor, so it wears the heading\'s color', () => {
        const html = heading('bolt', false);
        const mark = html.slice(at(html, 'data-group-icon="bolt"'), at(html, 'session-sidebar-group__label'));
        expect(mark).toMatch(/currentColor/);
        expect(/#[0-9a-f]{3,6}\b|rgb\(/i.test(mark)).toBe(false);
    });
    it('a reserved band never draws a picked icon', () => {
        heading('flask', false);
        Store.save(['cloude_a'], ['cloude_a'], []);
        const html = drawList([{ ...ROWS[0], is_pinned: true }]);
        const start = html.indexOf('data-group-toggle="pinned"');
        expect(start).toBeGreaterThan(-1);
        expect(html.slice(start, html.indexOf('</div>', start))).not.toContain('data-group-icon');
    });
});
