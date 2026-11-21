import { describe, expect, it } from 'vitest';
import { mergeLiveRow, type DrawerRow } from './fetch';
import { stamp } from './row-identity';

const records = [
    { id: 48, session_uuid: 'u-live', tmux_name: 'carnivore_Lantern App', tmux_created_epoch: 1790703623 },
    { id: 72, session_uuid: 'u-dead', tmux_name: 'carnivore_Lantern App', tmux_created_epoch: 1790006881 },
    { id: 90, session_uuid: 'u-solo', tmux_name: 'carnivore_solo', tmux_created_epoch: 1790703999 },
];

describe('a live row carries the wrapper session_uuid', () => {
    it('takes it from the listing with no records read, even when two records share the name', () => {
        const rows: DrawerRow[] = [];
        mergeLiveRow(rows, { tmux_session: 'carnivore_Lantern App', session_row_id: 48, session_uuid: 'u-live' });
        expect(rows[0]?.session_uuid).toBe('u-live');
        expect(stamp(rows, [])).toBe(1);
    });
    it('overwrites an asleep twin row of the same name with the live wrapper uuid', () => {
        const rows: DrawerRow[] = [{ name: 'carnivore_solo', session_uuid: 'u-old' }];
        mergeLiveRow(rows, { tmux_session: 'carnivore_solo', session_row_id: 90, session_uuid: 'u-solo' });
        expect(rows[0]?.session_uuid).toBe('u-solo');
    });
    it('leaves a row with a row id and no uuid unstamped: the server sends it, no guess', () => {
        const rows: DrawerRow[] = [];
        mergeLiveRow(rows, { tmux_session: 'carnivore_Lantern App', session_row_id: 48 });
        expect(stamp(rows, records)).toBe(0);
    });
});
