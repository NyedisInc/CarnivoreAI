import { describe, expect, test } from 'vitest';
import { setLocale } from '../i18n/index.svelte';
import { sleepHoldParts, sleepHoldText } from './sleep-hold';

setLocale('en');
const NOW = Date.parse('2026-10-01T22:30:00Z');
const hold = (reasons: string[]) => ({ reasons, text: '' });

describe('sleepHoldText', () => {
  test('null for no hold, no row, or reasons the client does not know', () => {
    expect(sleepHoldText(null, NOW)).toBeNull();
    expect(sleepHoldText({ sleep_hold: null }, NOW)).toBeNull();
    expect(sleepHoldText({ sleep_hold: hold(['mystery']) }, NOW)).toBeNull();
  });

  test('timers name the count and the time to the next fire', () => {
    const row = { sleep_hold: hold(['timers']), timers_live: 2, timers_next_fire_at: '2026-10-01T22:52:00Z' };
    expect(sleepHoldText(row, NOW)).toBe('kept awake: 2 live timers, next fires in 22m');
    expect(sleepHoldParts({ ...row, timers_next_fire_at: null }, NOW)).toBe('2 live timers');
  });

  test('background, subagents and unmeasured join with a semicolon', () => {
    const row = { sleep_hold: hold(['subagents', 'background', 'unmeasured']), subagents_running: 1, background_open: 3 };
    expect(sleepHoldText(row, NOW)).toBe(
      'kept awake: 1 subagent running; 3 background shells running; could not measure its timers or background work',
    );
    expect(sleepHoldParts({ sleep_hold: hold(['background']), background_open: 1 }, NOW)).toBe('background shell running');
  });
});
