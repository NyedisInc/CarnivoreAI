import { beforeEach, describe, expect, test } from 'vitest';

import { GLOBAL_NAME, inputFocus, publishInputFocus } from './input-focus.svelte';

interface PublishedFocus {
  current(): string | null;
  permits(id: string): boolean;
}

beforeEach(() => {
  inputFocus.release(inputFocus.owner ?? '');
});

describe('ownership moves only through claim and release', () => {
  test('nobody owns input until a cell claims it', () => {
    expect(inputFocus.owner).toBe(null);
  });

  test('a claim names the owner and the next claim replaces it', () => {
    inputFocus.claim('terminal:ses_a');
    expect(inputFocus.owner).toBe('terminal:ses_a');
    inputFocus.claim('terminal:ses_b');
    expect(inputFocus.owner).toBe('terminal:ses_b');
  });

  test('a release from a cell that no longer owns input changes nothing', () => {
    inputFocus.claim('terminal:ses_a');
    inputFocus.claim('terminal:ses_b');
    inputFocus.release('terminal:ses_a');
    expect(inputFocus.owner).toBe('terminal:ses_b');
  });

  test('a release from the owner gives it up', () => {
    inputFocus.claim('terminal:ses_a');
    inputFocus.release('terminal:ses_a');
    expect(inputFocus.owner).toBe(null);
  });

  test('an empty claim is ignored', () => {
    inputFocus.claim('terminal:ses_a');
    inputFocus.claim('');
    expect(inputFocus.owner).toBe('terminal:ses_a');
  });
});

describe('permits refuses only on a positive disagreement', () => {
  test('an unclaimed value permits everyone', () => {
    expect(inputFocus.permits('terminal:ses_a')).toBe(true);
    expect(inputFocus.permits('terminal:@primary')).toBe(true);
  });

  test('a claimed value permits its owner and refuses every other cell', () => {
    inputFocus.claim('terminal:ses_a');
    expect(inputFocus.permits('terminal:ses_a')).toBe(true);
    expect(inputFocus.permits('terminal:ses_b')).toBe(false);
    expect(inputFocus.permits('terminal:@primary')).toBe(false);
  });
});

describe('the published handle is a view of the module, not a copy', () => {
  test('it answers the live value, both before and after a claim', () => {
    const target: Record<string, unknown> = {};
    publishInputFocus(target);
    const published = target[GLOBAL_NAME] as PublishedFocus;

    expect(published.current()).toBe(null);
    inputFocus.claim('terminal:ses_a');
    expect(published.current()).toBe('terminal:ses_a');
    expect(published.permits('terminal:ses_a')).toBe(true);
    expect(published.permits('terminal:ses_b')).toBe(false);
  });

  test('importing the module is enough for the window to carry it', () => {
    const onGlobal = (globalThis as Record<string, unknown>)[GLOBAL_NAME] as PublishedFocus;
    expect(typeof onGlobal?.current).toBe('function');
    inputFocus.claim('terminal:ses_c');
    expect(onGlobal.current()).toBe('terminal:ses_c');
  });
});
