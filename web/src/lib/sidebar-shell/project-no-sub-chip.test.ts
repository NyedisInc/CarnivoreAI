/** @vitest-environment jsdom */
import { beforeAll, beforeEach, expect, it } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as Store from '../drawer/store';
import * as GroupStore from '../drawer/group-store';

beforeAll(() => { loadLegacyDrawer(); });
beforeEach(() => { resetDrawer(); });

const row = (name: string, over: Record<string, unknown> = {}): Record<string, unknown> => ({
    name, created_by_cloude: true, status: 'working', unread: false, is_pinned: false, subagents_running: 2, ...over,
});

it('draws the rollup chip on a group heading but not on a project heading', () => {
    const rows = [row('cloude_a', { project_id: 1, project_name: 'one' }), row('cloude_b')];
    Store.save([], rows.map((r) => r.name as string), []);
    GroupStore.apply({ status: 'ok', groups: [{ group_uuid: 'g1', name: 'crew', position: 0, members: ['cloude_b'] }] });
    drawList(rows);
    const list = document.getElementById('session-sidebar-list')!;
    const heads = (kind: string): Element[] => [...list.querySelectorAll(`.session-sidebar-group__headerrow[data-band-kind="${kind}"]`)];
    expect(heads('project').length).toBe(1);
    expect(heads('group').length).toBe(1);
    expect(heads('project')[0]!.querySelector('.subagent-count--rollup')).toBeNull();
    expect(heads('group')[0]!.querySelector('.subagent-count--rollup')).not.toBeNull();
});
