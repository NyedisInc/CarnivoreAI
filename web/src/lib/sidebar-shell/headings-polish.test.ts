/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { beforeAll, beforeEach, describe, it } from 'vitest';
import { drawList, loadLegacyDrawer, paintDrawer, resetDrawer } from './legacy-fixture';
import { unmountPanel } from '../mount';
import * as Density from '../drawer/density';
import * as Store from '../drawer/store';
import * as GroupStore from '../drawer/group-store';

const row = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
    name: 'cloude_a', created_by_cloude: true, status: 'working', unread: false,
    is_pinned: false, project_id: 7, project_name: 'cloudecode', ...over,
});

function sectionSlice(html: string, group: string): string {
    const markerIdx = html.indexOf(`data-group="${group}"`);
    assert.ok(markerIdx > -1, `setup: the ${group} section is drawn`);
    const start = html.lastIndexOf('<div', markerIdx);
    let depth = 0;
    let i = start;
    while (i < html.length) {
        const nextOpen = html.indexOf('<div', i);
        const nextClose = html.indexOf('</div>', i);
        if (nextClose === -1) return html.slice(start);
        if (nextOpen !== -1 && nextOpen < nextClose) {
            depth += 1;
            i = nextOpen + 4;
        } else {
            depth -= 1;
            i = nextClose + 6;
            if (depth === 0) return html.slice(start, i);
        }
    }
    return html.slice(start);
}

function draw(rows: Record<string, unknown>[], collapsed: string[] = [], pinned: string[] = []): string {
    Store.save(pinned, rows.map((r) => r.name as string), collapsed);
    return drawList(rows);
}

function assertChevronLightName(collapsedHtml: string, expandedHtml: string): void {
    const chevronIdx = collapsedHtml.indexOf('session-sidebar-group__chevron');
    const ledIdx = collapsedHtml.indexOf('session-sidebar-group__project-led');
    const labelIdx = collapsedHtml.indexOf('session-sidebar-group__label');
    assert.ok(chevronIdx > -1, 'the chevron is drawn');
    assert.ok(ledIdx > -1, 'the light is drawn while collapsed');
    assert.ok(labelIdx > -1, 'the name is drawn');
    assert.ok(chevronIdx < ledIdx && ledIdx < labelIdx, 'order is chevron, then light, then name');
    assert.match(collapsedHtml.slice(ledIdx, labelIdx), /class="status-led"/, 'the light slot holds the LED');
    assert.ok(ledIdx < collapsedHtml.indexOf('</button>'), 'the light sits inside the fold button, not trailing after it');
    assert.ok(!expandedHtml.includes('session-sidebar-group__project-led'),
        'no light element at all, and no reserved gap for one, while expanded');
}

function headOf(section: string): string {
    const body = section.indexOf('session-sidebar-group__body');
    return body === -1 ? section : section.slice(0, body);
}

beforeAll(() => {
    loadLegacyDrawer();
});

beforeEach(() => {
    resetDrawer();
    Density.setMode('cozy');
});

describe('a company heading folds on the first click', () => {
    it('folds and unfolds on the first click, not the next one', () => {
        const listEl = document.createElement('div');
        listEl.id = 'session-sidebar-list';
        document.body.appendChild(listEl);
        unmountPanel(listEl.id);
        const c = { listEl, _rows: [row({})], _listing: { ok: true }, _dragging: false };
        paintDrawer(c);
        assert.match(listEl.innerHTML, /data-company-open="1"/, 'setup: the heading starts open');
        Store.toggleCollapsed('c:orphaned');
        paintDrawer(c);
        assert.match(listEl.innerHTML, /data-company-open="0"/, 'the fold must paint on the repaint the click asks for');
        Store.toggleCollapsed('c:orphaned');
        paintDrawer(c);
        assert.match(listEl.innerHTML, /data-company-open="1"/, 'and unfold the same way');
        listEl.remove();
    });
});

describe('issue #625: chevron, then light (collapsed only), then name', () => {
    it('PINNED draws no light at all, folded or not (Alex (Example-owner), 2026-10-12, #1687)', () => {
        const collapsed = headOf(sectionSlice(draw([row()], ['pinned'], ['cloude_a']), 'pinned'));
        const expanded = headOf(sectionSlice(draw([row()], [], ['cloude_a']), 'pinned'));
        assert.ok(collapsed.includes('session-sidebar-group__chevron'), 'setup: the pinned heading is drawn, folded');
        assert.ok(!collapsed.includes('session-sidebar-group__project-led'), 'no light while folded');
        assert.ok(!expanded.includes('session-sidebar-group__project-led'), 'no light while open');
        assert.ok(collapsed.indexOf('session-sidebar-group__chevron') < collapsed.indexOf('session-sidebar-group__label'), 'chevron, then name');
        assert.ok(!collapsed.includes('session-sidebar-group__count'), 'no count element is drawn');
        assert.match(collapsed, /\(1 agent\)/, 'the count lives on in the title');
    });

    it('a company heading', () => {
        const openHtml = draw([row()]);
        const openStart = openHtml.indexOf('data-group-toggle="c:orphaned"');
        const openHead = openHtml.slice(openStart, openHtml.indexOf('session-sidebar-group__body', openStart));
        const collapsedHtml = draw([row()], ['c:orphaned']);
        const collapsedStart = collapsedHtml.indexOf('data-group-toggle="c:orphaned"');
        const collapsedHead = collapsedHtml.slice(collapsedStart, collapsedHtml.indexOf('session-sidebar-group__body', collapsedStart));
        assertChevronLightName(collapsedHead, openHead);
        assert.ok(!collapsedHead.includes('session-sidebar-group__count'));
    });

    it('a real project section', () => {
        const collapsed = headOf(sectionSlice(draw([row()], ['p:7']), 'p:7'));
        const expanded = headOf(sectionSlice(draw([row()]), 'p:7'));
        assertChevronLightName(collapsed, expanded);
    });

    it('ROGUE AGENTS', () => {
        const rogue = row({ project_id: null, project_name: null });
        const collapsed = headOf(sectionSlice(draw([rogue], ['rogue']), 'rogue'));
        const expanded = headOf(sectionSlice(draw([rogue]), 'rogue'));
        assertChevronLightName(collapsed, expanded);
    });

    it('a hand-made group, which keeps its kebab', () => {
        GroupStore.apply({ status: 'ok', groups: [{ group_uuid: 'g1', name: 'work stuff', position: 0, members: ['cloude_a'] }] });
        const key = GroupStore.bandKeyFor('g1');
        const collapsed = headOf(sectionSlice(draw([row()], [key]), key));
        const expanded = headOf(sectionSlice(draw([row()]), key));
        assertChevronLightName(collapsed, expanded);
        assert.ok(collapsed.includes('session-sidebar-group__menu'), 'a hand-made group keeps its kebab');
        assert.ok(collapsed.indexOf('session-sidebar-group__menu') > collapsed.indexOf('</button>'),
            'the kebab still trails the fold button; only the light moved');
    });
});
