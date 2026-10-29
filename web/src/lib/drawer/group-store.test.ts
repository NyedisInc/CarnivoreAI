import assert from 'node:assert/strict';
import { it } from 'vitest';
import { freshDrawer } from './test-support';

async function loadStore() {
    return (await freshDrawer({})).GroupStore;
}

function okBody(groups: unknown[]): Record<string, unknown> {
    return { status: 'ok', groups, detail: null };
}

function plain(value: unknown): unknown {
    return JSON.parse(JSON.stringify(value));
}


it('a fresh store is unknown, not ok and not unavailable', async () => {
    const S = await loadStore();
    assert.equal(S.current().status, 'unknown');
    assert.equal(S.isUsable(), false, 'unknown must not draw group chrome');
});

it('an ok body with no groups is usable and says nothing', async () => {
    const S = await loadStore();
    S.apply(okBody([]));
    assert.equal(S.current().status, 'ok');
    assert.equal(S.isUsable(), true);
    assert.equal(S.noticeText(), null, 'no groups is not a notice-worthy state');
});

it('an unavailable body is NOT usable and DOES say why', async () => {
    const S = await loadStore();
    S.apply({ status: 'unavailable', groups: [], detail: 'datastore missing' });
    assert.equal(S.current().status, 'unavailable');
    assert.equal(S.isUsable(), false);
    const notice = S.noticeText();
    assert.ok(notice, 'an unreadable group table must be said out loud');
    assert.ok(
        notice.includes('datastore missing'),
        `the notice must carry the reason, got ${JSON.stringify(notice)}`,
    );
});

it('a malformed body is unavailable, never an empty group list', async () => {
    for (const bad of [null, undefined, 'nope', 42, {}, { status: 'ok' }, { status: 'ok', groups: 'x' }] as unknown[]) {
        const S = await loadStore();
        S.apply(bad);
        assert.equal(
            S.current().status, 'unavailable',
            `body ${JSON.stringify(bad)} was graded as something other than unavailable`,
        );
        assert.equal(S.isUsable(), false);
    }
});

it('markUnavailable clears a previously good membership index', async () => {
    const S = await loadStore();
    S.apply(okBody([{ group_uuid: 'u1', name: 'work', position: 0, members: ['a'] }]));
    assert.equal(S.groupOf('a'), 'u1');
    S.markUnavailable('the fetch threw');
    assert.equal(S.groupOf('a'), null, 'a stale membership survived an unavailable read');
    assert.equal(S.bandOf('a', false), 'other');
});


it('dropping into pinned leaves the filing ALONE', async () => {
    const S = await loadStore();
    const intent = S.bandIntent('pinned');
    assert.equal(intent.pinned, true);
    assert.equal(
        'group' in intent && intent.group === undefined, true,
        'pinned must carry group:undefined (leave it alone), not null (remove it)',
    );
});

it('dropping into OTHER REMOVES the filing', async () => {
    const S = await loadStore();
    const intent = S.bandIntent('other');
    assert.deepEqual(plain(intent), { pinned: false, group: null });
});

it('dropping into a group files it there and unpins', async () => {
    const S = await loadStore();
    const intent = S.bandIntent('g:u1');
    assert.deepEqual(plain(intent), { pinned: false, group: 'u1' });
});

it('the pinned and other intents are distinguishable from each other', async () => {
    const S = await loadStore();
    const pinnedGroup = S.bandIntent('pinned').group;
    const otherGroup = S.bandIntent('other').group;
    assert.notEqual(
        pinnedGroup === undefined, otherGroup === undefined,
        'pinned and other must not both mean the same thing about filing',
    );
});


it('band order is pinned, then groups in position order, then other', async () => {
    const S = await loadStore();
    S.apply(okBody([
        { group_uuid: 'b', name: 'second', position: 1, members: [] },
        { group_uuid: 'a', name: 'first', position: 0, members: [] },
    ]));
    assert.deepEqual(plain(S.bandOrder()), ['pinned', 'g:a', 'g:b', 'other']);
});

it('a position tie falls back to uuid so the order is total', async () => {
    const S = await loadStore();
    S.apply(okBody([
        { group_uuid: 'zzz', name: 'z', position: 0, members: [] },
        { group_uuid: 'aaa', name: 'a', position: 0, members: [] },
    ]));
    assert.deepEqual(plain(S.bandOrder()), ['pinned', 'g:aaa', 'g:zzz', 'other'],
        'a tie fell back to payload order instead of to group_uuid',
    );
});

it('with groups unusable the band order is the pre-groups two-band list', async () => {
    const S = await loadStore();
    S.markUnavailable('nope');
    assert.deepEqual(plain(S.bandOrder()), ['pinned', 'other']);
});

it('pinned wins over a row group, because a row is drawn once', async () => {
    const S = await loadStore();
    S.apply(okBody([{ group_uuid: 'u1', name: 'work', position: 0, members: ['a'] }]));
    assert.equal(S.bandOf('a', false), 'g:u1', 'unpinned, it sits in its group');
    assert.equal(S.bandOf('a', true), 'pinned', 'pinned, it sits in the pinned band');
});

it('a group named "pinned" is still a user group, not the reserved band', async () => {
    const S = await loadStore();
    S.apply(okBody([{ group_uuid: 'u1', name: 'pinned', position: 0, members: ['a'] }]));
    assert.equal(
        S.bandOf('a', false), 'g:u1',
        'the label collided with a reserved band key - only the g: prefix may decide',
    );
    assert.equal(S.labelFor('g:u1'), 'pinned');
    assert.equal(S.labelFor('pinned'), 'pinned');
    assert.notEqual(S.bandIntent('g:u1').group, undefined);
});

it('groupUuidOf reads a group key and refuses a reserved one', async () => {
    const S = await loadStore();
    assert.equal(S.groupUuidOf('g:abc'), 'abc');
    assert.equal(S.groupUuidOf('pinned'), null);
    assert.equal(S.groupUuidOf('other'), null);
    assert.equal(S.groupUuidOf(''), null);
    assert.equal(S.groupUuidOf(null), null);
});

it('labelFor names a band that no longer exists rather than rendering blank', async () => {
    const S = await loadStore();
    S.apply(okBody([]));
    const label = S.labelFor('g:vanished');
    assert.ok(label && label.trim(), 'a missing group rendered as an empty label');
    assert.notEqual(label.trim(), '');
});

it('a group with no members contributes a band but no membership', async () => {
    const S = await loadStore();
    S.apply(okBody([{ group_uuid: 'u1', name: 'empty', position: 0, members: [] }]));
    assert.deepEqual(plain(S.bandOrder()), ['pinned', 'g:u1', 'other']);
    assert.equal(S.groupOf('anyone'), null);
});

it('a row in no group lands in other', async () => {
    const S = await loadStore();
    S.apply(okBody([{ group_uuid: 'u1', name: 'work', position: 0, members: ['a'] }]));
    assert.equal(S.bandOf('b', false), 'other');
});


it('isFilingBand: pinned, other and a real group are filing targets', async () => {
    const S = await loadStore();
    assert.equal(S.isFilingBand('pinned'), true);
    assert.equal(S.isFilingBand('other'), true);
    assert.equal(S.isFilingBand('g:u1'), true);
});

it('isFilingBand: a project key, rogue, and garbage are NOT filing targets', async () => {
    const S = await loadStore();
    assert.equal(S.isFilingBand('p:42'), false);
    assert.equal(S.isFilingBand('rogue'), false);
    assert.equal(S.isFilingBand(''), false);
    assert.equal(S.isFilingBand(null), false);
    assert.equal(S.isFilingBand(undefined), false);
});


it('isProjectsOpen defaults OPEN with nothing stored', async () => {
    const S = await loadStore();
    assert.equal(S.isProjectsOpen(), true);
});

it('setProjectsOpen persists and toggleProjectsOpen flips it', async () => {
    const S = await loadStore();
    assert.equal(S.setProjectsOpen(false), false);
    assert.equal(S.isProjectsOpen(), false, 'the cached read reflects the write');
    assert.equal(S.toggleProjectsOpen(), true);
    assert.equal(S.isProjectsOpen(), true);
});

