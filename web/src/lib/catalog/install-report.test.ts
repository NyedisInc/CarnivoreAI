import { describe, expect, test } from 'vitest';

import { installsView } from './install-report';
import type { ItemInstalls } from './types';

/** An item three people have reported installing. */
const COUNTED: ItemInstalls = {
    item_id: 'example-owner/sme',
    count: 3,
    by_version: { '1.0.0': 1, '1.1.0': 2 },
};

describe('a count this app could not read', () => {
    test('a failed read is `unavailable` and carries NO count', () => {
        const view = installsView(null);
        expect(view.shape).toBe('unavailable');
        expect(view.count).toBeNull();
    });

    test('a count that is not a usable number is unavailable, never zero', () => {
        expect(installsView({ count: 'lots' } as unknown as ItemInstalls).count).toBeNull();
        expect(installsView({ count: null } as ItemInstalls).shape).toBe('unavailable');
        expect(installsView({ count: -1 } as ItemInstalls).shape).toBe('unavailable');
        expect(installsView({ count: NaN } as ItemInstalls).shape).toBe('unavailable');
        expect(installsView({ count: true } as unknown as ItemInstalls).shape).toBe(
            'unavailable',
        );
    });

    test('NEGATIVE CONTROL AND ITS PAIR: a real zero is NOT unavailable', () => {
        const measured = installsView({ count: 0, by_version: {} } as ItemInstalls);
        expect(measured.shape).toBe('none');
        expect(measured.count).toBe(0);

        const counted = installsView(COUNTED);
        expect(counted.shape).toBe('counted');
        expect(counted.count).toBe(3);
    });

    test('a fractional count is floored rather than printed as a fraction', () => {
        expect(installsView({ count: 2.7 } as ItemInstalls).count).toBe(2);
    });
});
