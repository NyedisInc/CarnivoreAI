import { describe, expect, test } from 'vitest';
import { composerGhost, tabAccepts } from './chat-model';

describe("the agent terminal's suggested next prompt is the empty composer's ghost text (#2617)", () => {
  test('the empty box shows it and Tab fills it in', () => {
    expect(composerGhost('', 'run the tests')).toBe('run the tests');
    expect(tabAccepts('Tab', '', 'run the tests')).toBe('run the tests');
  });

  test('typing anything hides it, and Tab then does nothing of ours', () => {
    expect(composerGhost('r', 'run the tests')).toBe('');
    expect(tabAccepts('Tab', 'r', 'run the tests')).toBeNull();
  });

  test('no suggestion, or another key: nothing', () => {
    expect(composerGhost('', null)).toBe('');
    expect(tabAccepts('Tab', '', null)).toBeNull();
    expect(tabAccepts('Enter', '', 'run the tests')).toBeNull();
    expect(tabAccepts('Escape', '', 'run the tests')).toBeNull();
  });
});
