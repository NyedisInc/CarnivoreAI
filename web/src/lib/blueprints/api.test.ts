import { describe, expect, test } from 'vitest';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { blueprintError } from './api';

describe('blueprintError', () => {
    test('reads the object-shaped detail every blueprint route answers', () => {
        const err = new ApiError('refused', 409, null, {
            detail: { code: 'blueprint_name_taken', detail: 'a blueprint with that name already exists' },
        });
        const refusal = blueprintError(err);
        expect(refusal.code).toBe('blueprint_name_taken');
        expect(refusal.detail).toBe('a blueprint with that name already exists');
        expect(refusal.status).toBe(409);
    });

    test('reads the list-shaped detail a request-validation refusal answers', () => {
        const err = new ApiError('bad request', 400, null, {
            detail: [
                { loc: ['body', 'spec', 'sessions', 0, 'family'], msg: 'field required', type: 'missing' },
                { loc: ['body', 'spec', 'name'], msg: 'string too long', type: 'string_too_long' },
            ],
        });
        const refusal = blueprintError(err);
        expect(refusal.detail).toBe('field required; string too long');
        expect(refusal.detail).not.toMatch(/answered/i);
        expect(refusal.detectors).toEqual([]);
    });

    test('a list-shaped detail with no readable msg falls back to the status message, never blank', () => {
        const err = new ApiError('the server answered 400', 400, null, { detail: [{ loc: ['body'] }] });
        expect(blueprintError(err).detail).toBe('the server answered 400');
    });

    test('a non-ApiError (network failure) reads its own message', () => {
        expect(blueprintError(new Error('fetch failed')).detail).toBe('fetch failed');
        expect(blueprintError(new Error('fetch failed')).status).toBe(0);
    });
});
