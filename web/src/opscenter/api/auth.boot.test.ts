
import { describe, expect, it } from 'vitest';
import { decideBootState } from './auth.svelte';

describe('decideBootState', () => {
  it('opens signed-out when neither token is held', () => {
    expect(decideBootState(false, false)).toBe('signed-out');
  });

  it('opens signed-in when an access token is held, optimistically, with no refresh token', () => {
    expect(decideBootState(true, false)).toBe('signed-in');
  });

  it('opens signed-in when both tokens are held', () => {
    expect(decideBootState(true, true)).toBe('signed-in');
  });

  it('opens signed-out when only a refresh token is held: nothing to present to a read today', () => {
    expect(decideBootState(false, true)).toBe('signed-out');
  });
});
