/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { beforeAll, beforeEach, describe, it } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as Density from '../drawer/density';
import * as Store from '../drawer/store';
import * as GroupStore from '../drawer/group-store';
import { reconcile } from '../drawer/store-rebind';

beforeAll(() => { loadLegacyDrawer(); });

beforeEach(() => {
    resetDrawer();
    Density.setMode('compact');
    GroupStore.apply({
        status: 'ok',
        groups: [{ group_uuid: 'g1', name: 'alpha crew', position: 0, members: ['cloude_a'] }],
    });
});

function row(name: string, projectId: number, extra: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        name, label: name, status: 'idle', unread: false, is_pinned: false, project_id: projectId,
        project_name: `Proj${projectId}`, created_by_cloude: true, session_id: `ses_${name}`,
        session_uuid: `su-${name}`, kind: 'agent', ...extra,
    };
}

function folds(html: string): Record<string, string> {
    const out: Record<string, string> = {};
    for (const m of html.matchAll(/data-group="([^"]+)"[^>]*data-collapsed="([01])"/g)) out[m[1]!] = m[2]!;
    return out;
}

function fetchAndPaint(rows: Record<string, unknown>[]): string {
    reconcile(rows as Array<{ name: string; session_uuid?: string | null }>);
    return drawList(rows);
}

describe('kill a session from the row menu path', () => {
    it.each([
        ['a middle member', 'cloude_b'],
        ['the last row of its project', 'cloude_c'],
        ['the last member of a group', 'cloude_a'],
    ])('every fold survives (%s)', (_label, victim) => {
        const all = [row('cloude_a', 10), row('cloude_b', 10), row('cloude_c', 11)];
        Store.save([], all.map((r) => r.name as string), ['p:10', 'p:11', 'g:g1', 'other']);
        fetchAndPaint(all);
        const before = Store.current().collapsed.slice();
        const drawnBefore = folds(drawList(all));
        const after = all.filter((r) => r.name !== victim);
        const html = fetchAndPaint(after);
        assert.deepEqual(Store.current().collapsed, before, 'the stored fold list is unchanged');
        const drawnAfter = folds(html);
        for (const key of Object.keys(drawnAfter)) {
            if (key in drawnBefore) assert.equal(drawnAfter[key], drawnBefore[key], `${key} keeps its fold`);
        }
        const back = folds(fetchAndPaint(all));
        assert.deepEqual(back, drawnBefore);
    });
});
