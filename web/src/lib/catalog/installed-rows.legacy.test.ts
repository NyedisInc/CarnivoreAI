import { describe, expect, it } from 'vitest';
import { groupInstalled } from './installed-rows';

describe('legacy publisher rows (#2923)', () => {
    it('a nyedis row reads as installed for the same-named carnivore item, unless that item has its own row', () => {
        const old = { item_id: 'nyedis/snes', scope: 'global' } as never;
        expect(groupInstalled([old])['carnivore/snes']).toEqual([old]);
        const own = { item_id: 'carnivore/snes', scope: 'global' } as never;
        expect(groupInstalled([old, own])['carnivore/snes']).toEqual([own]);
        expect(groupInstalled([])['carnivore/snes']).toBeUndefined();
    });
});
