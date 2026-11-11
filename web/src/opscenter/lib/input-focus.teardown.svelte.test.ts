/** @vitest-environment jsdom */
import { describe, it, expect, afterEach } from 'vitest';
import { flushSync } from 'svelte';
import { inputFocus } from './input-focus.svelte';

describe('input focus teardown (#2916)', () => {
  afterEach(() => { inputFocus.forget('terminal:A'); inputFocus.forget('terminal:B'); });

  it('a teardown forget in the flush of another claim does not null the fresh claim', () => {
    let tick = $state(0);
    inputFocus.claim('terminal:A');
    const stop = $effect.root(() => {
      $effect(() => {
        void tick;
        return () => inputFocus.forget('terminal:A');
      });
    });
    flushSync();
    inputFocus.release('terminal:A');
    inputFocus.claim('terminal:B');
    tick = 1;
    flushSync();
    stop();
    expect(inputFocus.owner).toBe('terminal:B');
    expect(inputFocus.permits('terminal:A')).toBe(false);
  });
});
