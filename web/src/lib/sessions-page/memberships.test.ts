import { describe, expect, it } from 'vitest';
import { NONE, isNone, membershipsOf, type GroupLike, type LayoutLike } from './memberships';

const L: LayoutLike = { layout_uuid: 'lay-1', name: 'review desk', members: [{ session_uuid: 's1' }, { session_uuid: 's2' }] };
const OTHER_LAYOUT: LayoutLike = { layout_uuid: 'lay-2', name: 'other', members: [{ session_uuid: 's9' }] };
const G: GroupLike = { group_uuid: 'grp-1', name: 'hotfixes', member_session_uuids: ['s1'] };
const OTHER_GROUP: GroupLike = { group_uuid: 'grp-2', name: 'later', member_session_uuids: ['s9'] };

describe('membershipsOf', () => {
    it('a session in layout L and group G yields both, and nothing else', () => {
        const m = membershipsOf('s1', [OTHER_LAYOUT, L], [OTHER_GROUP, G]);
        expect(m).toEqual({ layouts: [{ uuid: 'lay-1', name: 'review desk' }], groups: [{ uuid: 'grp-1', name: 'hotfixes' }] });
        expect(isNone(m)).toBe(false);
    });

    it('a layout without a group keeps the groups list empty', () => {
        expect(membershipsOf('s2', [L], [G])).toEqual({ layouts: [{ uuid: 'lay-1', name: 'review desk' }], groups: [] });
    });

    it('an unknown session is none', () => {
        const m = membershipsOf('nobody', [L, OTHER_LAYOUT], [G, OTHER_GROUP]);
        expect(m).toBe(NONE);
        expect(isNone(m)).toBe(true);
    });
});
