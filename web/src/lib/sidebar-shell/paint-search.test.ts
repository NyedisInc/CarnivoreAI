/** @vitest-environment jsdom */
import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { loadLegacyDrawer, paintDrawer, resetDrawer } from './legacy-fixture';
import { unmountPanel } from '../mount';
import * as Density from '../drawer/density';
import * as Search from '../drawer/search';

let listEl: HTMLElement;

function rows(): Record<string, unknown>[] {
    return [
        { name: 'cloude_orchard', created_by_cloude: true, status: 'idle', project_id: 1, project_name: 'P', kind: 'agent' },
        { name: 'cloude_other', created_by_cloude: true, status: 'idle', project_id: 1, project_name: 'P', kind: 'agent' },
    ];
}

function makeCtrl(r: Record<string, unknown>[]): Record<string, unknown> {
    return { listEl, _rows: r, _listing: { ok: true }, _dragging: false };
}

function drawn(): string[] {
    return [...listEl.querySelectorAll('.session-sidebar-row[data-name]')].map((e) => e.getAttribute('data-name') as string);
}

beforeAll(() => {
    listEl = document.createElement('div');
    listEl.id = 'session-sidebar-list';
    listEl.className = 'session-sidebar-list';
    document.body.appendChild(listEl);
    loadLegacyDrawer();
});

beforeEach(() => {
    resetDrawer();
    Density.setMode('compact');
    unmountPanel(listEl.id);
});

describe('the query and the repaint', () => {
    it('the query rides into the paint: only the matching row is drawn, and the list says a search is active', () => {
        Search.setQuery('orchard');
        paintDrawer(makeCtrl(rows()));
        expect(drawn()).toEqual(['cloude_orchard']);
        expect(listEl.getAttribute('data-search-active')).toBe('1');
    });

    it('a query change alone forces a real repaint, even with the same rows', () => {
        const ctrl = makeCtrl(rows());
        paintDrawer(ctrl);
        expect(drawn().sort()).toEqual(['cloude_orchard', 'cloude_other']);
        Search.setQuery('orchard');
        paintDrawer(ctrl);
        expect(drawn(), 'the query alone must be enough to change the picture').toEqual(['cloude_orchard']);
    });

    it('SURVIVES REPAINT: a poll tick with new row objects keeps applying the SAME live query', () => {
        const ctrl = makeCtrl(rows());
        Search.setQuery('orchard');
        paintDrawer(ctrl);
        expect(drawn()).toEqual(['cloude_orchard']);
        ctrl._rows = rows().map((r) => ({ ...r, unread: true }));
        paintDrawer(ctrl);
        expect(drawn(), 'the filter must still be applied after an unrelated repaint').toEqual(['cloude_orchard']);
    });

    it('an unchanged query on an unchanged picture rewrites nothing: the row is the same DOM node', () => {
        const ctrl = makeCtrl(rows());
        Search.setQuery('orchard');
        paintDrawer(ctrl);
        const before = listEl.querySelector('.session-sidebar-row[data-name="cloude_orchard"]');
        const html = listEl.innerHTML;
        paintDrawer(ctrl);
        expect(listEl.querySelector('.session-sidebar-row[data-name="cloude_orchard"]')).toBe(before);
        expect(listEl.innerHTML).toBe(html);
    });

    it('clearing the query is itself a change that repaints back to the unfiltered picture', () => {
        const ctrl = makeCtrl(rows());
        Search.setQuery('orchard');
        paintDrawer(ctrl);
        Search.setQuery('');
        paintDrawer(ctrl);
        expect(drawn().sort()).toEqual(['cloude_orchard', 'cloude_other']);
        expect(listEl.getAttribute('data-search-active')).toBe('0');
    });
});
