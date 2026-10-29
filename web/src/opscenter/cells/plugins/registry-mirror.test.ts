import { describe, expect, test } from 'vitest';

import { BUILTIN } from '../../../lib/plugins/builtin';
import { PLUGIN_REGISTRY } from './registry-mirror';

describe('registry-mirror', () => {
    test('lists every BUILTIN plugin with its surfaces and contribution count', () => {
        expect(BUILTIN.length).toBeGreaterThan(0);
        expect(PLUGIN_REGISTRY.map((row) => row.id)).toEqual(BUILTIN.map((plugin) => plugin.id).sort());
        for (const plugin of BUILTIN) {
            const row = PLUGIN_REGISTRY.find((entry) => entry.id === plugin.id)!;
            const surfaces = [...new Set(plugin.contributions.map((c) => c.surface))];
            expect(row.contributionCount, plugin.id).toBe(surfaces.length);
            expect([...row.surfaces], plugin.id).toEqual(surfaces);
        }
    });

    test('the comparison can fail: a row for a plugin that is not registered is caught', () => {
        const ids = [...PLUGIN_REGISTRY.map((row) => row.id), 'ghost'];
        expect(ids).not.toEqual(BUILTIN.map((plugin) => plugin.id).sort());
    });
});
