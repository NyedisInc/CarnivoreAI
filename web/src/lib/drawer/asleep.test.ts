import assert from 'node:assert/strict';
import { it } from 'vitest';
import { freshDrawer } from './test-support';

const REC = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
    session_uuid: 'u-a', tmux_name: 'carnivore_a', tmux_created_epoch: 100,
    title: 'fix the deploy', asleep: true, archived_at: null, owned: true, ...over,
});

it('an asleep record becomes a row, painted asleep and keyed on its uuid', async () => {
    const w = { SessionSidebarAsleep: (await freshDrawer({})).Asleep };
    const rows: Array<Record<string, unknown>> = [];
    assert.equal(w.SessionSidebarAsleep.addRows(rows, [REC()]), 1);
    assert.equal(rows[0]!.name, 'carnivore_a');
    assert.equal(rows[0]!.asleep, true);
    assert.equal(rows[0]!.status, 'asleep');
    assert.equal(rows[0]!.session_uuid, 'u-a');
    assert.equal(rows[0]!.session_id, null, 'an asleep row has no live backend to attach');
});

it('a live row holding the name, a deleted or a waking record adds nothing', async () => {
    const w = { SessionSidebarAsleep: (await freshDrawer({})).Asleep };
    const live = [{ name: 'carnivore_a', status: 'working' }];
    assert.equal(w.SessionSidebarAsleep.addRows(live, [REC()]), 0);
    assert.equal(live.length, 1);
    const rows: Array<Record<string, unknown>> = [];
    assert.equal(w.SessionSidebarAsleep.addRows(rows, [
        REC({ archived_at: '2026-09-01T00:00:00Z' }),
        REC({ asleep: false }),
        REC({ tmux_name: null }),
    ]), 0);
    assert.equal(w.SessionSidebarAsleep.addRows(rows, [REC()]), 1);
});

it('an asleep record carries its follow-up flag onto the row (issue #749)', async () => {
    const w = { SessionSidebarAsleep: (await freshDrawer({})).Asleep };
    const rows: Array<Record<string, unknown>> = [];
    w.SessionSidebarAsleep.addRows(rows, [
        REC({ unread: true }),
        REC({ session_uuid: 'u-b', tmux_name: 'carnivore_b' }),
        REC({ session_uuid: 'u-c', tmux_name: 'carnivore_c', unread: null }),
    ]);
    assert.deepEqual(rows.map((r) => r.unread), [true, false, false],
        'only an explicit true paints; an older server (absent) and null read unflagged');
});

it('a Layout member keeps its row when a newer asleep twin shares its tmux name (#1217)', async () => {
    const w = { SessionSidebarAsleep: (await freshDrawer({})).Asleep };
    const recs = [
        REC({ session_uuid: 'u-twin', tmux_name: 'carnivore_p' }),
        REC({ session_uuid: 'u-member', tmux_name: 'carnivore_p' }),
    ];
    const plain: Array<Record<string, unknown>> = [];
    w.SessionSidebarAsleep.addRows(plain, recs);
    assert.deepEqual(plain.map((r) => r.session_uuid), ['u-twin'], 'no Layout: newest twin keeps the name');
    const rows: Array<Record<string, unknown>> = [];
    w.SessionSidebarAsleep.addRows(rows, recs, new Set(['u-member']));
    assert.deepEqual(rows.map((r) => r.session_uuid), ['u-member'], 'the Layout member wins the name');
});

it('an asleep record keeps the alarm icon words for what will wake it, and null stays null (issue #1903)', async () => {
    const w = { SessionSidebarAsleep: (await freshDrawer({})).Asleep };
    const rows: Array<Record<string, unknown>> = [];
    w.SessionSidebarAsleep.addRows(rows, [
        REC({ automations_state: 'ok', automations_total: 2, automations_enabled: 2, automations_next: [{ name: 'sweep', enabled: true, next_fire_at: 9 }] }),
        REC({ session_uuid: 'u-b', tmux_name: 'carnivore_b' }),
    ]);
    assert.equal(rows[0]!.automations_state, 'ok');
    assert.equal(rows[0]!.automations_total, 2);
    assert.equal(rows[0]!.automations_enabled, 2);
    assert.equal((rows[0]!.automations_next as unknown[]).length, 1);
    assert.equal(rows[1]!.automations_state, null, 'not measured stays null, never none');
});
