import { describe, expect, test } from 'vitest';

import * as Led from './led';
import { legacy } from './led-legacy-fixture';

describe('the vocabularies', () => {
    test('THE DRIFT GUARD: the port\'s vocabularies ARE the legacy ones', () => {
        const real = legacy();
        expect([...Led.INNER_STATES]).toEqual(real.INNER_STATES);
        expect([...Led.OUTER_STATES]).toEqual(real.OUTER_STATES);
    });

    test('NEGATIVE CONTROL: the drift guard can actually fail', () => {
        const real = legacy();
        expect(real.INNER_STATES.length).toBeGreaterThan(0);
        expect(real.OUTER_STATES.length).toBeGreaterThan(0);
        expect([...Led.INNER_STATES]).not.toEqual([...real.INNER_STATES, 'banana']);
        expect([...Led.INNER_STATES]).not.toEqual(real.OUTER_STATES);
    });
});
