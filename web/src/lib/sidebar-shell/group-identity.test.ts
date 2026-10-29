// @vitest-environment jsdom
import assert from 'node:assert/strict';
import { beforeAll, it } from 'vitest';
import * as Arrangement from '../drawer/arrangement';
import * as GroupOrder from '../drawer/group-order';
import * as GroupStore from '../drawer/group-store';
import * as Identity from '../drawer/row-identity';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';

beforeAll(() => { loadLegacyDrawer(); });

function loadStack() {
    resetDrawer();
    return { A: Arrangement, GS: GroupStore, ID: Identity, ORD: GroupOrder };
}

function row(over: Record<string, unknown> = {}): Record<string, unknown> & { name: string } {
    return {
        name: 'carnivore_a', created_by_cloude: true, created_at_epoch: 1_790_000_000,
        status: 'idle', unread: false, is_pinned: false, project_id: 7, project_name: 'acme', ...over,
    };
}

const STALE_GROUPS = {
    status: 'ok', detail: null,
    groups: [{
        group_uuid: 'g1', name: 'Joe', position: 0,
        members: ['cloude_c', 'cloude_a', 'cloude_b'],
        member_session_uuids: ['U-C', 'U-A', 'U-B'],
    }],
};

const LIVE = [
    row({ name: 'carnivore_a', created_at_epoch: 101 }),
    row({ name: 'carnivore_b', created_at_epoch: 102 }),
    row({ name: 'carnivore_c', created_at_epoch: 103 }),
    row({ name: 'carnivore_loose', created_at_epoch: 104 }),
];
const RECORDS = [
    { session_uuid: 'U-A', tmux_name: 'carnivore_a', tmux_created_epoch: 101 },
    { session_uuid: 'U-B', tmux_name: 'carnivore_b', tmux_created_epoch: 102 },
    { session_uuid: 'U-C', tmux_name: 'carnivore_c', tmux_created_epoch: 103 },
    { session_uuid: 'U-L', tmux_name: 'carnivore_loose', tmux_created_epoch: 104 },
];

function section(html: string, key: string): string | null {
    const marker = `<div class="session-sidebar-group" role="group" data-group="${key}"`;
    const start = html.indexOf(marker);
    if (start === -1) return null;
    const rest = html.slice(start + marker.length);
    const next = rest.search(/<div class="session-sidebar-group[ "]/);
    return marker + (next === -1 ? rest : rest.slice(0, next));
}

function namesIn(html: string | null): string[] {
    if (!html) return [];
    return Array.from(html.matchAll(/class="session-sidebar-row[^"]*"[^>]*data-name="([^"]+)"/g)).map((m) => m[1] as string);
}

function paint(_s: unknown, rows: Array<Record<string, unknown> & { name: string }>): string {
    return drawList(rows);
}

it('a renamed session stays in its group, in the stored member order', async () => {
    const s = loadStack();
    const rows = LIVE.map((r) => ({ ...r }));
    s.ID.stamp(rows as Identity.IdentityRow[], RECORDS);
    s.GS.setIdentities(rows as Array<{ name: string; session_uuid?: string | null }>);
    s.GS.apply(STALE_GROUPS);
    const html = paint(s, rows);
    assert.deepEqual(namesIn(section(html, 'g:g1')), ['carnivore_c', 'carnivore_a', 'carnivore_b'],
        'every renamed member is in its group, in member_session_uuids order');
    assert.equal(s.GS.groupOf('carnivore_loose'), null,
        'a genuinely unfiled row is not resolved into any group');
});

it('NEGATIVE CONTROL: without the uuid join the renamed rows fall into ungrouped', async () => {
    const s = loadStack();
    const rows = LIVE.map((r) => ({ ...r }));
    s.GS.apply(STALE_GROUPS);
    const html = paint(s, rows);
    assert.equal(namesIn(section(html, 'g:g1')).length, 0);
    for (const r of rows) {
        assert.equal(s.GS.groupOf(r.name), null,
            `${r.name} is not resolved into any group without the uuid join`);
    }
});

it('NEGATIVE CONTROL: a reused name does not inherit the old session\'s group', async () => {
    const s = loadStack();
    const rows = [row({ name: 'cloude_a', created_at_epoch: 500 })];
    s.ID.stamp(rows as Identity.IdentityRow[], [{ session_uuid: 'U-NEW', tmux_name: 'cloude_a', tmux_created_epoch: 500 }]);
    s.GS.setIdentities(rows as Array<{ name: string; session_uuid?: string | null }>);
    s.GS.apply(STALE_GROUPS);
    assert.equal(s.GS.groupOf('cloude_a'), null);
});

it('an unstamped row falls back to its name', async () => {
    const s = loadStack();
    s.GS.apply(STALE_GROUPS);
    assert.equal(s.GS.groupOf('cloude_a'), 'g1');
    assert.equal(s.GS.memberRank('cloude_a'), 1);
});

it('the identity join refuses to guess', async () => {
    const s = loadStack();
    const idx = s.ID.recordIndex([
        { session_uuid: 'X', tmux_name: 'dup', tmux_created_epoch: 1 },
        { session_uuid: 'Y', tmux_name: 'dup', tmux_created_epoch: 2 },
        { session_uuid: 'Z', tmux_name: 'solo', tmux_created_epoch: 3 },
        { session_uuid: 'OLD', tmux_name: 'solo', tmux_created_epoch: 9, archived_at: '2026-01-01' },
    ]);
    assert.equal(s.ID.uuidFor({ name: 'dup', created_at_epoch: 2 }, idx), 'Y', 'the instance join is exact');
    assert.equal(s.ID.uuidFor({ name: 'dup', created_at_epoch: 0 }, idx), null, 'two live records: no guess');
    assert.equal(s.ID.uuidFor({ name: 'solo', created_at_epoch: 0 }, idx), 'Z', 'one live record: joined');
    assert.equal(s.ID.uuidFor({ name: 'nobody', created_at_epoch: 0 }, idx), null);
});

it('a changed live name set is noticed, an unchanged one is not', async () => {
    const s = loadStack();
    s.ID.reset();
    assert.equal(s.ID.namesChanged([{ name: 'cloude_a' }]), false, 'the first sighting only records');
    assert.equal(s.ID.namesChanged([{ name: 'cloude_a' }]), false);
    assert.equal(s.ID.namesChanged([{ name: 'carnivore_a' }]), true, 'a rename re-reads the groups');
});

it('an in-group move writes the band order, keeping unseen members', async () => {
    const s = loadStack();
    assert.deepEqual([...s.ORD.nextOrder(['U-B', 'U-A'], ['U-A', 'U-B', 'U-IMPORTED'])],
        ['U-B', 'U-A', 'U-IMPORTED']);
});

