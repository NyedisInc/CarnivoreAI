/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeAll, beforeEach, it } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as Density from '../drawer/density';
import * as Store from '../drawer/store';
import * as GroupStore from '../drawer/group-store';
import * as Bucketing from '../drawer/bucketing';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const repoFile = (...parts: string[]): string => fs.readFileSync(path.join(ROOT, ...parts), 'utf8');
const plain = (x: unknown): any => JSON.parse(JSON.stringify(x));

beforeAll(() => {
    loadLegacyDrawer();
});

beforeEach(() => {
    resetDrawer();
});

function row(over: Record<string, unknown> = {}): Record<string, any> {
    return {
        name: 'cloude_a', created_by_cloude: true, created_at_epoch: 1_700_000_000,
        status: 'working', unread: false, is_pinned: false, ...over,
    };
}

function bodyHtml(rows: Record<string, any>[], density: string,
    arrangement: { collapsed?: string[] } | null, opts: { dragging?: boolean }): string {
    Density.setMode(density);
    Store.save(rows.filter((r) => r.is_pinned).map((r) => r.name), rows.map((r) => r.name),
        (arrangement && arrangement.collapsed) || []);
    return drawList(rows, { _dragging: !!opts.dragging });
}

function headerHtml(key: string, count: number, collapsed: boolean, rows?: Record<string, any>[]): string {
    assert.ok(key === 'pinned' || key === 'rogue', 'the shim draws the PINNED or ROGUE heading only');
    const base = (rows && rows[0]) || row({ status: 'idle' });
    const drawn = Array.from({ length: count }, (_, i) => ({ ...base, name: `p${i}`, is_pinned: key === 'pinned' }));
    const html = bodyHtml(drawn, 'cozy', { collapsed: collapsed ? [key] : [] }, {});
    const start = html.lastIndexOf('<div', html.indexOf(`data-group="${key}"`));
    return html.slice(start, html.indexOf('session-sidebar-group__body', start));
}

const G = {
    bodyHtml,
    headerHtml,
    split: (rows: Record<string, any>[]) => Bucketing.split(rows as Array<{ name: string }>),
};

/**
 * Description: the (inner, outer) pair on one section header's summary
 *   LED. Scoped to that section's own slice of the markup so a two-group
 *   render cannot have one header's light read for another's.
 * Inputs: html (string) - a bodyHtml render. key (string) - band key.
 * Output: object|null - {inner, outer}, or null when no LED is present.
 */
function headerLed(html: string, key: string): { inner: string; outer: string } | null {
    const start = html.indexOf(`data-group="${key}"`);
    if (start < 0) return null;
    const next = html.indexOf('data-group="', start + 1);
    const slice = html.slice(start, next < 0 ? html.length : next);
    const led = slice.indexOf('session-sidebar-group__project-led');
    if (led < 0) return null;
    const m = slice
        .slice(led)
        .match(/data-inner="([^"]+)" data-outer="([^"]+)"/);
    return m ? { inner: m[1] as string, outer: m[2] as string } : null;
}

it('ITEM 64: an EMPTY pinned group renders nothing, not a bare header', () => {
    const html = G.bodyHtml([row({ name: 'a' }), row({ name: 'b' })], 'cozy', null, {});
    assert.ok(!html.includes('data-group="pinned"'),
        'a header for a band the user has never put anything in asks a question nobody asked');
});

it('ITEM 64: with nothing pinned or grouped, rows file under PROJECTS/ROGUE AGENTS', () => {
    const html = G.bodyHtml([row({ name: 'a' })], 'cozy', null, {});
    assert.ok(html.includes('data-name="a"'), 'the row still renders');
    assert.ok(!html.includes('>other<'), 'the old band name is gone');
    assert.ok(html.includes('data-group="rogue"'), 'and files under ROGUE AGENTS instead');
});

it('ITEM 64: the seam appears exactly when there IS a seam', () => {
    const html = G.bodyHtml(
        [row({ name: 'p', is_pinned: true }), row({ name: 'a', project_id: 1, project_name: 'one' })], 'cozy', null, {});
    assert.ok(html.includes('data-group="pinned"'), 'the pinned group is drawn');
    assert.ok(html.includes('data-company-open'), 'and the company heading is drawn below it');
    assert.ok(html.indexOf('data-group="pinned"') < html.indexOf('data-company-open'),
        'pinned comes FIRST, which is the whole request');
});

it('ITEM 64: a drag in flight draws the EMPTY pinned group as a drop target', () => {
    const html = G.bodyHtml([row({ name: 'a' })], 'cozy', null, { dragging: true });
    assert.ok(html.includes('data-group="pinned"'),
        'an empty pinned group must be droppable DURING a drag');
    assert.ok(html.includes('data-count="0"'), 'and it says it is empty');
});

it('ITEM 64: the moment the drag ends the empty group disappears again', () => {
    const during = G.bodyHtml([row({ name: 'a' })], 'cozy', null, { dragging: true });
    const after = G.bodyHtml([row({ name: 'a' })], 'cozy', null, { dragging: false });
    assert.ok(during.includes('data-group="pinned"'));
    assert.ok(!after.includes('data-group="pinned"'), 'steady state is still rule 1');
});

it('ITEM 64: a COLLAPSED group emits no rows at all, not hidden ones', () => {
    const rows = [row({ name: 'p', is_pinned: true }), row({ name: 'a' })];
    const html = G.bodyHtml(rows, 'cozy', { collapsed: ['pinned'] }, {});
    const bodies = html.split('session-sidebar-group__body');
    assert.ok(html.includes('data-collapsed="1"'), 'the group reports itself collapsed');
    assert.ok(!html.includes('data-band="pinned"'),
        'the collapsed pinned band renders no row instance at all');
    assert.ok(html.includes('data-name="a"'), 'the open group still renders');
    assert.ok(bodies.length > 1, 'the body element still exists so aria-controls resolves');
});

it('ITEM 64: a collapsed group still SAYS how much it hides', () => {
    const rows = [
        row({ name: 'p', is_pinned: true }), row({ name: 'q', is_pinned: true }),
        row({ name: 'a' }),
    ];
    const html = G.bodyHtml(rows, 'cozy', { collapsed: ['pinned'] }, {});
    assert.ok(/data-group="pinned" data-section="pinned" data-collapsed="1" data-count="2"/.test(html),
        'or a collapsed group and an empty one look identical');
});

it('ITEM 64: the header carries aria-expanded matching the fold', () => {
    const rows = [row({ name: 'p', is_pinned: true }), row({ name: 'a' })];
    const open = G.bodyHtml(rows, 'cozy', { collapsed: [] }, {});
    const shut = G.bodyHtml(rows, 'cozy', { collapsed: ['pinned'] }, {});
    assert.ok(open.includes('aria-expanded="true"'));
    assert.ok(shut.includes('aria-expanded="false"'),
        'the fold must not be shape-only - a chevron is not an announcement');
});

it('ITEM 64: split() reads is_pinned and never re-decides it', () => {
    const bands = G.split([
        row({ name: 'p', is_pinned: true }), row({ name: 'a' }), row({ name: 'b' }),
    ]);
    assert.deepEqual(plain(bands.pinned).map((r: { name: string }) => r.name), ['p']);
    assert.deepEqual(plain(bands.other).map((r: { name: string }) => r.name), ['a', 'b']);
});

it('a PINNED session ALSO renders under its project - duplicated, not moved', () => {
    const rows = [row({ name: 'p', is_pinned: true, project_id: 9, project_name: 'acme' })];
    const html = G.bodyHtml(rows, 'cozy', null, {});
    assert.ok(html.includes('data-group="pinned"'), 'the pinned band is drawn');
    assert.ok(html.includes('id="session-sidebar-row__p__pinned"'),
        'carrying the pinned instance of the row');
    assert.ok(html.includes('data-group="p:9"'), 'and its project section is drawn too');
    assert.ok(html.includes('id="session-sidebar-row__p__p:9"'),
        'carrying a SEPARATE instance of the same row, not the same node twice');
    assert.ok(/data-group="p:9"[\s\S]{0,2000}>acme</.test(html),
        'the project section is labelled by project_name');
});

it('a project_name: null row (no project_id) lands in ROGUE AGENTS', () => {
    const rows = [row({ name: 'a', project_id: null, project_name: null })];
    const html = G.bodyHtml(rows, 'cozy', null, {});
    assert.ok(html.includes('data-group="rogue"'), 'it files under the reserved rogue band');
    assert.ok(html.includes('id="session-sidebar-row__a__rogue"'));
    assert.ok(/data-group="rogue"[\s\S]{0,2000}>rogue agents</.test(html),
        'rendered as "rogue agents" (CSS uppercases every header to ROGUE AGENTS)');
});

it('duplicated rows carry unique ids and the correct data-band each', () => {
    const rows = [row({
        name: 'dup', is_pinned: true, project_id: 3, project_name: 'proj',
    })];
    const html = G.bodyHtml(rows, 'cozy', null, {});
    const ids = Array.from(html.matchAll(/id="(session-sidebar-row__[^"]+)"/g)).map((m) => m[1]);
    assert.deepEqual(ids.sort(), [
        'session-sidebar-row__dup__p:3',
        'session-sidebar-row__dup__pinned',
    ], 'exactly two DOM instances, each with its own id');
    assert.ok(html.includes('data-band="pinned"') && html.includes('data-band="p:3"'),
        'and each instance carries the band it was rendered under');
});

it('a company fold hides every project section under it at once', () => {
    const rows = [
        row({ name: 'a', project_id: 1, project_name: 'one' }),
        row({ name: 'b', project_id: 2, project_name: 'two' }),
        row({ name: 'c', project_id: null, project_name: null }),
    ];
    const open = G.bodyHtml(rows, 'cozy', null, {});
    assert.ok(open.includes('data-group="p:1"') && open.includes('data-group="p:2"')
        && open.includes('data-group="rogue"'), 'every section renders while open');
    assert.ok(open.includes('data-company-open="1"'));

    const shut = G.bodyHtml(rows, 'cozy', { collapsed: ['c:orphaned'] }, {});
    assert.ok(!shut.includes('data-group="p:1"'), 'project one is gone');
    assert.ok(!shut.includes('data-group="p:2"'), 'project two is gone');
    assert.ok(shut.includes('data-group="rogue"'), 'rogue agents are their own band now');
    assert.ok(shut.includes('data-company-open="0"'), 'the heading itself stays, marked shut');
    assert.ok(shut.includes('aria-expanded="false"'));
});

it('a reserved band draws NO kebab, and nothing is left reading for one', () => {
    const html = G.bodyHtml(
        [row({ name: 'p', is_pinned: true }), row({ name: 'a' })], 'compact', null, {});
    assert.ok(!html.includes('data-group-menu-band'),
        'the reserved-band kebab attribute must not be emitted anywhere');
    assert.ok(!html.includes('session-sidebar-group__menu'),
        'and no kebab button either, for pinned or for other');
    GroupStore.apply({ status: 'ok', groups: [{ group_uuid: 'u1', name: 'work', position: 0, members: ['a'] }] });
    const grouped = G.bodyHtml([row({ name: 'p', is_pinned: true }), row({ name: 'a' })], 'compact', null, {});
    assert.ok(grouped.includes('data-group-menu="u1"'), 'a REAL group keeps its rename/reorder/delete kebab');
    assert.equal((grouped.match(/session-sidebar-group__menu/g) || []).length, 1, 'and it is the only kebab');
});

it('a reserved header still pays for the kebab column, so the LED stays in line', () => {
    const html = G.headerHtml('pinned', 3, false, undefined);
    assert.ok(html.includes('data-band-kind="reserved"'),
        'the header row says which kind it is, so the stylesheet can reserve the width');
    const css = repoFile('client', 'css', 'session-sidebar-groups.css');
    assert.ok(
        /\[data-band-kind="reserved"\]\s*\{[^}]*padding-right:\s*26px/.test(css),
        'the reserved band reserves the 20px button plus its 6px margin');
});

it('the gutter holds the chevron, and a COLLAPSED header reads chevron, light, then name', () => {
    const html = G.headerHtml('rogue', 3, true, [row({ status: 'working' })]);
    const gutter = html.slice(html.indexOf('session-sidebar-group__gutter'),
        html.indexOf('session-sidebar-group__label'));
    assert.ok(gutter.includes('session-sidebar-group__chevron'), 'the chevron is in the gutter');
    assert.ok(html.indexOf('data-group-toggle') < html.indexOf('session-sidebar-group__gutter'),
        'the gutter is inside the fold toggle, so clicking the chevron folds');
    const chevronIdx = html.indexOf('session-sidebar-group__chevron');
    const ledIdx = html.indexOf('session-sidebar-group__project-led');
    const labelIdx = html.indexOf('session-sidebar-group__label');
    assert.ok(ledIdx > -1, 'a COLLAPSED header draws the light');
    assert.ok(chevronIdx < ledIdx && ledIdx < labelIdx, 'order is chevron, then light, then name');
    assert.ok(ledIdx < html.indexOf('</button>'), 'the light sits inside the fold button');
    assert.match(html.slice(ledIdx, labelIdx), /class="status-led"/, 'the light slot holds the LED');
    assert.ok(!html.includes('session-sidebar-group__count'), 'no count is drawn');
});

it('an EXPANDED header draws no light and no gap for one', () => {
    const html = G.headerHtml('rogue', 3, false, [row({ status: 'working' })]);
    assert.ok(html.includes('session-sidebar-group__label'), 'setup: the header is drawn');
    assert.ok(!html.includes('session-sidebar-group__project-led'),
        'no light element at all while the header is expanded');
});

it('a PINNED header draws no light, folded or not (Alex (Example-owner), 2026-10-12, #1687)', () => {
    const folded = G.headerHtml('pinned', 3, true, [row({ status: 'working' })]);
    assert.ok(folded.includes('session-sidebar-group__label'), 'setup: the folded pinned header is drawn');
    assert.ok(!folded.includes('session-sidebar-group__project-led'), 'no light while folded');
    assert.ok(!G.headerHtml('pinned', 3, false, [row({ status: 'working' })]).includes('session-sidebar-group__project-led'),
        'no light while open');
});

it('the header LED reads the ROWS, and says what a group holds (issue #625: collapsed only)', () => {
    const rows = [
        row({ name: 'p', project_id: 1, project_name: 'one', status: 'idle' }),
        row({ name: 'q', project_id: 1, project_name: 'one', status: 'idle' }),
        row({ name: 'a', status: 'working' }),
    ];
    const html = G.bodyHtml(rows, 'cozy', { collapsed: ['p:1', 'rogue'] }, {});
    assert.deepEqual(headerLed(html, 'p:1'), { inner: 'idle', outer: 'steady' },
        'an all-idle section is idle, not unknown');
    assert.deepEqual(headerLed(html, 'rogue'), { inner: 'working', outer: 'active' },
        'and a section holding a working session says so');
});

it('a COLLAPSED group is still summarised, from rows it does not render', () => {
    const rows = [
        row({ name: 'p', project_id: 1, project_name: 'one', status: 'question' }),
        row({ name: 'a', status: 'idle' }),
    ];
    const html = G.bodyHtml(rows, 'cozy', { collapsed: ['p:1'] }, {});
    assert.ok(!html.includes('data-band="p:1"'),
        'its row instance really is absent from the folded band');
    assert.deepEqual(headerLed(html, 'p:1'),
        { inner: 'waiting-permission', outer: 'active' },
        'and the header still reports the parked session inside it');
});

it('issue #625: the light only draws while collapsed, but the roll-up itself is unchanged by the fold', () => {
    const rows = [
        row({ name: 'p', project_id: 1, project_name: 'one', status: 'working' }),
        row({ name: 'q', project_id: 1, project_name: 'one', status: 'idle', unread: true }),
        row({ name: 'a', status: 'idle' }),
    ];
    const open = G.bodyHtml(rows, 'cozy', { collapsed: [] }, {});
    const shut = G.bodyHtml(rows, 'cozy', { collapsed: ['p:1'] }, {});
    assert.equal(headerLed(open, 'p:1'), null,
        'expanded draws no light at all - #625, superseding the old always-on aggregate');
    assert.deepEqual(headerLed(shut, 'p:1'), { inner: 'working', outer: 'active' },
        'collapsed draws the same roll-up the rows would always have produced');
});

it('a header over live members NEVER reads unknown', () => {
    const states = ['working', 'question', 'notice', 'finished_unread', 'idle', 'dead'];
    for (const state of states) {
        const rows = [
            row({ name: 'p', project_id: 1, project_name: 'one', status: state }),
            row({ name: 'a', status: 'idle' }),
        ];
        const html = G.bodyHtml(rows, 'cozy', { collapsed: ['p:1'] }, {});
        const led = headerLed(html, 'p:1');
        assert.ok(led, `a header with a ${state} member renders a LED`);
        assert.notEqual(led.inner, 'unknown', `${state} member must not read unknown`);
        assert.notEqual(led.outer, 'dim', `${state} member must not read dim`);
    }
});
