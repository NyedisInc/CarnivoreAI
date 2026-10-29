import { describe, expect, it } from 'vitest';
import { ApiError } from '../../../opscenter/api/auth.svelte';
import { errorText } from './error-text';

const failure = (detail: unknown): ApiError => new ApiError('HTTP 422', 422, null, { detail });

describe('errorText', () => {
    it('reads a string detail', () => expect(errorText(failure('too long'))).toBe('too long'));
    it('reads a nested detail', () => expect(errorText(failure({ detail: 'nested' }))).toBe('nested'));
    it('joins a 422 list', () => expect(errorText(failure(['a: b', 'c: d']))).toBe('a: b; c: d'));
    it('falls back to the message, then to a plain error', () => {
        expect(errorText(failure(undefined))).toBe('HTTP 422');
        expect(errorText(new Error('boom'))).toBe('boom');
    });
});
