import { describe, expect, it } from 'vitest';
import { indexLeaders } from './leaders';
import { isBandOrderKey, isFoldKey, isSpawnedFoldKey } from '../drawer/store-keys';
import type { SidebarRow } from './legacy';

const roster = [
    { id: 1, rank: 'alpha', display_name: 'Alpha', session_row_id: 10 },
    { id: 3, rank: 'project', display_name: 'Proj', session_row_id: 12, parent_id: 1 },
    { id: 4, rank: 'feature', display_name: 'Feat', session_row_id: 13, session_uuid: 'u-feat', parent_id: 3 },
    { id: 5, rank: 'task', display_name: 'Task', session_row_id: 14, parent_id: 4 },
    { id: 6, rank: 'feature', display_name: 'Direct feature', session_row_id: 15, parent_id: 1 },
    { id: 7, rank: 'task', display_name: 'Loop', session_row_id: 16, parent_id: 7 },
];
const row = (name: string, id: number | null, uuid?: string): SidebarRow => ({ name, session_row_id: id, session_uuid: uuid });

describe('agents a project agent spawned (issue #1464)', () => {
    const idx = indexLeaders(roster);

    it('marks workers with a project agent above them, by row id or uuid, never by name', () => {
        expect(idx.spawned?.(row('renamed', 13))).toBe(true);
        expect(idx.spawned?.(row('x', null, 'u-feat'))).toBe(true);
        expect(idx.spawned?.(row('t', 14))).toBe(true);
    });

    it('leaves leaders, directly launched and cyclic agents alone', () => {
        expect(idx.spawned?.(row('proj', 12))).toBe(false);
        expect(idx.spawned?.(row('direct', 15))).toBe(false);
        expect(idx.spawned?.(row('loop', 16))).toBe(false);
        expect(idx.spawned?.(row('stranger', 99))).toBe(false);
    });

    it('the fold key syncs as a p: key but is never a band-order key', () => {
        expect(isFoldKey('p:42:agents')).toBe(true);
        expect(isSpawnedFoldKey('p:42:agents')).toBe(true);
        expect(isSpawnedFoldKey('p:42')).toBe(false);
        expect(isBandOrderKey('p:42:agents')).toBe(false);
        expect(isBandOrderKey('p:42')).toBe(true);
    });
});
