import { describe, expect, it } from 'vitest';
import { timerStateKey, timerStateOf } from './timer-state';

describe('timerStateOf', () => {
  it('reads the four drawn words', () => {
    for (const word of ['ok', 'warning', 'error', 'disabled']) expect(timerStateOf(word)).toBe(word);
  });

  it('reads none, null and anything else as no state', () => {
    for (const word of ['none', null, undefined, '', 'green', 3]) expect(timerStateOf(word)).toBeNull();
  });

  it('every state has its own catalog key', () => {
    const keys = (['ok', 'warning', 'error', 'disabled'] as const).map(timerStateKey);
    expect(new Set(keys).size).toBe(4);
  });
});
