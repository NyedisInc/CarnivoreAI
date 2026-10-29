import { describe, expect, it } from 'vitest';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { apiErrorMessageOr, errorMessageOr, nonEmptyErrorMessageOr } from './failure-reason';

describe('failure-reason', () => {
  it('errorMessageOr keeps an empty Error message and falls back for non-errors', () => {
    expect(errorMessageOr(new Error('gone'), 'f')).toBe('gone');
    expect(errorMessageOr(new Error(''), 'f')).toBe('');
    expect(errorMessageOr('boom', 'f')).toBe('f');
  });
  it('nonEmptyErrorMessageOr falls back on an empty message', () => {
    expect(nonEmptyErrorMessageOr(new Error('gone'), 'f')).toBe('gone');
    expect(nonEmptyErrorMessageOr(new Error(''), 'f')).toBe('f');
    expect(nonEmptyErrorMessageOr(null, 'f')).toBe('f');
  });
  it('apiErrorMessageOr trusts only an ApiError sentence', () => {
    expect(apiErrorMessageOr(new ApiError('nope', 400, null), 'f')).toBe('nope');
    expect(apiErrorMessageOr(new Error('plain'), 'f')).toBe('f');
  });
});
