import { describe, expect, it } from 'vitest';
import { averagePackStats } from './pack-stats';

describe('averagePackStats (#3387)', () => {
    it('averages measured readings across hosts and ignores null/offline snapshots', () => {
        const avg = averagePackStats([
            { snapshot: { load: { busy_cores: 5.1, cores: 10, memory_percent: 65, disk_percent: 93 } } as never },
            { snapshot: { load: { busy_cores: 3.5, cores: 10, memory_percent: 64, disk_percent: 84 } } as never },
            { snapshot: { load: { busy_cores: 1.0, cores: 10, memory_percent: 61, disk_percent: null } } as never },
            { snapshot: null },
        ]);
        expect(avg).toEqual({ cpu: 32, ram: 63, disk: 89 });
    });

    it('returns all nulls when no host has a snapshot', () => {
        expect(averagePackStats([{ snapshot: null }])).toEqual({ cpu: null, ram: null, disk: null });
    });
});
