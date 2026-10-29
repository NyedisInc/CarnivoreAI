/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { icons } from '../../opscenter/ui/icons';
import { ROW_COLORS, ROW_ICONS, colorValue, isRowIcon, rowLooks, stampLooks, ROW_LOOKS_TOPIC } from '../open-files/row-looks';
import SidebarRow from './SidebarRow.svelte';
import { rowHost } from './row-host';
import { buildRowPlan } from './row-plan';

const ID = '0123456789abcdef';

function row(over: Record<string, unknown> = {}): Record<string, unknown> {
    return { name: `browser:${ID}`, kind: 'browser', browser_id: ID, file: true, file_kind: 'file', path: 'a.md', label: 'a.md', url: null, status: 'file', is_pinned: false, ...over };
}

function draw(r: Record<string, unknown>): { el: HTMLElement; stop: () => void } {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const app = mount(SidebarRow, { target, props: { r: buildRowPlan(r as never, 'compact', 'files', undefined, rowHost()) } });
    flushSync();
    return { el: target.querySelector('.session-sidebar-row') as HTMLElement, stop: () => { unmount(app); target.remove(); } };
}

describe('row looks', () => {
    afterEach(() => { document.body.innerHTML = ''; });

    it('an unstyled row draws the usual mark with no style attribute anywhere', () => {
        const { el, stop } = draw(row());
        expect(el.querySelector('.session-sidebar-row-provider')!.hasAttribute('style')).toBe(false);
        expect(el.querySelector('.session-sidebar-row-name')!.hasAttribute('style')).toBe(false);
        expect(el.querySelector('.session-sidebar-row-provider svg path')!.getAttribute('d')).toContain('M5 3h9l5 5v13H5Z');
        expect(el.querySelector('[data-icon]')).toBeNull();
        stop();
    });

    it('a color tints the mark and the name with a theme token; the mark stays', () => {
        const { el, stop } = draw(row({ look: { color: 'cyan', icon: null } }));
        expect(el.querySelector('.session-sidebar-row-provider')!.getAttribute('style')).toBe('color: var(--oc-cyan);');
        expect(el.querySelector('.session-sidebar-row-name')!.getAttribute('style')).toBe('color: var(--oc-cyan);');
        expect(el.querySelector('.session-sidebar-row-provider svg path')!.getAttribute('d')).toContain('M5 3h9l5 5v13H5Z');
        stop();
    });

    it('an icon replaces the mark on a file, a page and a browser row; the color is optional', () => {
        for (const over of [{}, { file: false, page: true }, { file: false, page: false, status: 'live' }]) {
            const { el, stop } = draw(row({ ...over, look: { color: null, icon: 'star' } }));
            const provider = el.querySelector('.session-sidebar-row-provider')!;
            expect(provider.querySelector('svg')!.getAttribute('data-icon')).toBe('star');
            expect(provider.hasAttribute('style')).toBe(false);
            stop();
        }
    });

    it('a review board row (a page row on the reviewboard tab) draws plain unset and wears its look set', () => {
        const board = { file: false, page: true, file_kind: null, path: null, label: 'bottom bar', url: '/static/popout.html?tab=reviewboard&board=20261013-bottom-bar', status: 'live' };
        const plain = draw(row(board));
        expect(plain.el.querySelector('.session-sidebar-row-provider')!.hasAttribute('style')).toBe(false);
        expect(plain.el.querySelector('.session-sidebar-row-name')!.hasAttribute('style')).toBe(false);
        expect(plain.el.querySelector('[data-icon]')).toBeNull();
        plain.stop();
        const styled = draw(row({ ...board, look: { color: 'violet', icon: 'star' } }));
        expect(styled.el.querySelector('.session-sidebar-row-provider')!.getAttribute('style')).toBe('color: var(--oc-violet);');
        expect(styled.el.querySelector('.session-sidebar-row-name')!.getAttribute('style')).toBe('color: var(--oc-violet);');
        expect(styled.el.querySelector('.session-sidebar-row-provider svg')!.getAttribute('data-icon')).toBe('star');
        styled.stop();
    });

    it('an unknown color or icon name draws nothing special', () => {
        const { el, stop } = draw(row({ look: { color: '#ff0000', icon: 'not-an-icon' } }));
        expect(el.querySelector('.session-sidebar-row-provider')!.hasAttribute('style')).toBe(false);
        expect(el.querySelector('[data-icon]')).toBeNull();
        stop();
    });

    it('stampLooks stamps only browser-kind rows that have a look', () => {
        const rows = [row(), row({ name: 'browser:ffffffffffffffff', browser_id: 'ffffffffffffffff' }), { name: 'cloude_a', kind: 'agent', browser_id: ID }];
        stampLooks(rows, { [ID]: { color: 'green', icon: null } });
        expect(rows[0]!.look).toEqual({ color: 'green', icon: null });
        expect(rows[1]!.look).toBeUndefined();
        expect(rows[2]!.look).toBeUndefined();
        stampLooks(rows, null);
    });

    it('the lists are the real icons and palette, and values are tokens', () => {
        expect([...ROW_COLORS]).toEqual(['orange', 'green', 'cyan', 'yellow', 'coral', 'violet', 'green-bright', 'yellow-bright']);
        expect(ROW_ICONS.filter((n) => !(n in icons))).toEqual([]);
        expect(colorValue('green-bright')).toBe('var(--oc-green-bright)');
        expect(colorValue('#fff')).toBeNull();
        expect(isRowIcon('docs') && !isRowIcon('nope')).toBe(true);
        expect(ROW_LOOKS_TOPIC).toBe('row_looks');
        expect(rowLooks).toBeDefined();
    });
});
