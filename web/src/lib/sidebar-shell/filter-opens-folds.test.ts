/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { afterEach, beforeAll, beforeEach, it } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as Density from '../drawer/density';
import * as Store from '../drawer/store';
import * as Search from '../drawer/search';
import { setCountFilter } from '../drawer/count-filter.svelte';
import { foldPresent } from '../drawer/fold-view';

beforeAll(() => {
    loadLegacyDrawer();
});

const FOLDED = ['p:10', 'pinned'];

beforeEach(() => {
    resetDrawer();
    Density.setMode('compact');
});

afterEach(() => {
    setCountFilter(null);
    Search.setQuery('');
});

function rows(): Record<string, any>[] {
    return [
        { name: 'cloude_alpha', label: 'Alpha', is_pinned: true, project_id: 10, project_name: 'ProjectFoo', status: 'working', created_by_cloude: true },
        { name: 'cloude_beta', label: 'Beta', is_pinned: false, project_id: 10, project_name: 'ProjectFoo', status: 'idle', created_by_cloude: true },
    ];
}

function draw(): string {
    const r = rows();
    Store.save(['cloude_alpha'], r.map((x) => x.name), FOLDED.slice());
    return drawList(r, {});
}

function collapsedOf(html: string, key: string): string | null {
    const m = new RegExp(`data-group="${key}"[^>]*data-collapsed="([01])"`).exec(html);
    return m ? m[1]! : null;
}

it('without a filter the stored folds are drawn', () => {
    const html = draw();
    assert.equal(collapsedOf(html, 'p:10'), '1');
    assert.equal(collapsedOf(html, 'pinned'), '1');
});

it('search text kept through a drag opens the folds that hold a match, writes nothing, and restores on clear', () => {
    draw();
    Search.setQuery('alpha');
    const html = drawList(rows(), { _dragging: true });
    assert.equal(collapsedOf(html, 'p:10'), '0');
    assert.equal(collapsedOf(html, 'pinned'), '0');
    assert.deepEqual(Store.current().collapsed, FOLDED);
    Search.setQuery('');
    const back = drawList(rows(), {});
    assert.equal(collapsedOf(back, 'p:10'), '1');
    assert.deepEqual(Store.current().collapsed, FOLDED);
});

it('the typed search lists AGENTS flat, writes nothing, and the stored folds come back on clear', () => {
    draw();
    Search.setQuery('alpha');
    const html = drawList(rows(), {});
    assert.ok(html.includes('data-group="search:agents"'));
    assert.equal(collapsedOf(html, 'p:10'), null, 'no project section while a text is listed');
    assert.deepEqual(Store.current().collapsed, FOLDED);
    Search.setQuery('');
    assert.equal(collapsedOf(drawList(rows(), {}), 'p:10'), '1');
});

it('the stats bar count filter does the same through the same mechanism', () => {
    draw();
    setCountFilter('working');
    const html = drawList(rows(), {});
    assert.equal(collapsedOf(html, 'p:10'), '0');
    assert.equal(collapsedOf(html, 'pinned'), '0');
    assert.deepEqual(Store.current().collapsed, FOLDED);
    setCountFilter(null);
    assert.equal(collapsedOf(drawList(rows(), {}), 'p:10'), '1');
    assert.deepEqual(Store.current().collapsed, FOLDED);
});

it('inverted keys (layout, spawned) read expanded and ordinary keys read open under a filter', () => {
    assert.equal(foldPresent('c:3', true, true), false);
    assert.equal(foldPresent('layout:u1', false, true), true);
    assert.equal(foldPresent('p:1:agents', false, true), true);
    assert.equal(foldPresent('c:3', true, false), true);
    assert.equal(foldPresent('layout:u1', false, false), false);
});
