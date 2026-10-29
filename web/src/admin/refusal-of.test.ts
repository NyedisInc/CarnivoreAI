import { expect, test } from 'vitest';
import { ApiRefusal } from './admin.js';
import { refusalOf } from './refusal-of';

test('a server refusal passes through and anything else is offline', () => {
    const refusal = { status: 401, code: 'expired', params: {} };
    expect(refusalOf(new ApiRefusal(refusal))).toBe(refusal);
    expect(refusalOf(new TypeError('fetch failed'))).toEqual({ status: 0, code: 'offline', params: {} });
});
