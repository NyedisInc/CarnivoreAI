import { describe, expect, it } from 'vitest';
import { fakeStorage, freshDrawer, type FakeStorage } from './test-support';
import { CURRENT_PREFIX, LEGACY_PREFIXES } from './store-rebind';

const KEY = 'carnivore.session.sidebar.arrangement';

async function load(envelope: Record<string, unknown>) {
    const storage: FakeStorage = fakeStorage({ [KEY]: JSON.stringify(envelope) });
    const d = await freshDrawer({ localStorage: storage });
    d.Store.load();
    return { S: d.Store, R: d.Rebind, storage };
}

const LIVE = [
    { name: 'carnivore_Mac', session_uuid: 'U-MAC' },
    { name: 'carnivore_N8N', session_uuid: 'U-N8N' },
    { name: 'carnivore_Hockey', session_uuid: 'U-H' },
];

describe('the rebind', () => {
    it('mirrors the product identity prefixes (tests/test_client_mirrors_server_constants.py reads the same pair)', () => {
        expect(CURRENT_PREFIX).toBe('carnivore_');
        expect([...LEGACY_PREFIXES]).toEqual(['cloude_']);
    });

    it('cloude_* pins against live carnivore_* rows come back pinned, in the same order', async () => {
        const { S, R, storage } = await load({ v: 1, pinned: ['cloude_N8N', 'cloude_Mac'],
            order: ['cloude_N8N', 'cloude_Hockey', 'cloude_Mac', 'cloude_gone'], collapsed: [] });
        const moved = R.reconcile(LIVE);
        expect(moved.length).toBe(3);
        expect([...S.current().pinned]).toEqual(['carnivore_N8N', 'carnivore_Mac']);
        expect([...S.current().order], 'the order holds, and an entry naming nothing live keeps its slot')
            .toEqual(['carnivore_N8N', 'carnivore_Hockey', 'carnivore_Mac', 'cloude_gone']);
        expect(S.isPinned('carnivore_Mac')).toBe(true);
        const saved = JSON.parse(storage.getItem(KEY) as string);
        expect(saved.v, "additive field, no version bump (the file's own versioning rule)").toBe(1);
        expect(saved.ids.carnivore_Mac, 'the uuid is recorded for the next rename').toBe('U-MAC');
    });

    it('the next rename resolves by uuid, not by prefix', async () => {
        const { S, R } = await load({ v: 1, pinned: ['carnivore_Mac'], order: [], collapsed: [], ids: { carnivore_Mac: 'U-MAC' } });
        R.reconcile([{ name: 'carnivore_Mac-2', session_uuid: 'U-MAC' }]);
        expect([...S.current().pinned]).toEqual(['carnivore_Mac-2']);
    });

    it('NEGATIVE CONTROL: an ambiguous match is not migrated', async () => {
        const { S, R } = await load({ v: 1, pinned: ['cloude_Mac', 'old_mac'], order: [], collapsed: [], ids: { old_mac: 'U-MAC' } });
        const moved = R.reconcile(LIVE);
        expect([...moved]).toEqual([]);
        expect([...S.current().pinned], 'both entries kept, neither guessed').toEqual(['cloude_Mac', 'old_mac']);
    });

    it('NEGATIVE CONTROL: a prefix swap that disagrees with the recorded uuid is refused', async () => {
        const { S, R } = await load({ v: 1, pinned: ['cloude_Mac'], order: [], collapsed: [], ids: { cloude_Mac: 'U-OTHER' } });
        R.reconcile(LIVE);
        expect([...S.current().pinned]).toEqual(['cloude_Mac']);
    });

    it('a live name already saved after the rename merges into the old slot', async () => {
        const { S, R } = await load({ v: 1, pinned: ['cloude_Mac'], order: ['cloude_Mac', 'carnivore_N8N', 'carnivore_Mac'], collapsed: [] });
        R.reconcile(LIVE);
        expect([...S.current().order]).toEqual(['carnivore_Mac', 'carnivore_N8N']);
        expect([...S.current().pinned]).toEqual(['carnivore_Mac']);
    });

    it('an unchanged arrangement is not rewritten on every poll', async () => {
        const { S, R, storage } = await load({ v: 1, pinned: ['carnivore_Mac'], order: ['carnivore_Mac'], collapsed: [],
            ids: { carnivore_Mac: 'U-MAC' } });
        const before = storage.getItem(KEY);
        R.reconcile([{ name: 'carnivore_Mac', session_uuid: 'U-MAC' }]);
        expect(storage.getItem(KEY)).toBe(before);
        expect(S.current().status).toBe('ok');
    });

    it("a per-band order (merged from Alex's line) follows a rename, and its ids survive the prune", async () => {
        const { S, R, storage } = await load({ v: 1, pinned: [], order: [], collapsed: [],
            bands: { 'p:7': ['cloude_Hockey', 'cloude_Mac'] }, ids: { carnivore_N8N: 'U-N8N' } });
        const moved = R.reconcile(LIVE);
        expect(moved.length, 'both band-only names moved').toBe(2);
        expect([...S.bandOrder('p:7')]).toEqual(['carnivore_Hockey', 'carnivore_Mac']);
        const saved = JSON.parse(storage.getItem(KEY) as string);
        expect(saved.ids.carnivore_Mac, 'a band-only name keeps its uuid for the next rename').toBe('U-MAC');
        R.reconcile([{ name: 'carnivore_Mac-2', session_uuid: 'U-MAC' }, LIVE[2]!]);
        expect([...S.bandOrder('p:7')], 'the next rename resolves by uuid').toEqual(['carnivore_Hockey', 'carnivore_Mac-2']);
    });
});
