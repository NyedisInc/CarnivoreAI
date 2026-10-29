import { describe, expect, it } from 'vitest';
import { mergeLiveRow, type DrawerRow } from './fetch';
import { stamp } from './row-identity';

const records = [
    { id: 48, session_uuid: 'u-live', tmux_name: 'carnivore_Example App', tmux_created_epoch: 1790703623 },
    { id: 72, session_uuid: 'u-dead', tmux_name: 'carnivore_Example App', tmux_created_epoch: 1790006881 },
];

describe('stamp joins a live-only row on its session_row_id', () => {
    it('picks the live record even when two unarchived records share the name', () => {
        const rows: DrawerRow[] = [];
        mergeLiveRow(rows, { tmux_session: 'carnivore_Example App', session_row_id: 48 });
        expect(stamp(rows, records)).toBe(1);
        expect(rows[0]?.session_uuid).toBe('u-live');
    });
    it('still leaves an ambiguous row unstamped without a row id', () => {
        const rows: DrawerRow[] = [];
        mergeLiveRow(rows, { tmux_session: 'carnivore_Example App' });
        expect(stamp(rows, records)).toBe(0);
    });
});
