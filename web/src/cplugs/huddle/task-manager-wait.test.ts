import { describe, expect, test } from 'vitest';
import type { HuddleItem } from './huddle-model';
import { waitChip, waitLine, type WaitWords } from './task-manager-wait';

const strings: Record<string, string> = {
  'cplug.huddle.wait.on': 'waiting on {what}, by {by}',
  'cplug.huddle.wait.check': 'checks itself: {kind}',
  'cplug.huddle.wait.check_kind.version_live': 'version live',
  'cplug.huddle.wait.extended': 'extended: {reason}',
  'cplug.huddle.wait.forks': 'waiting on its {count} forked tasks',
};
const words: WaitWords = {
  t: (key, params = {}) => Object.entries(params).reduce((text, [k, v]) => text.replace(`{${k}}`, String(v)), strings[key] ?? key),
  due: { today: 'today', tomorrow: 'tomorrow' },
};
const NOW = new Date(2026, 9, 13, 12, 0);
const wait = { waiting_on: 'staging restart', kind: 'install', set_at: 1, expect_by: new Date(2026, 9, 13, 15, 0).getTime() / 1000, deadline: 2, extended: 0, extend_reason: '', check_kind: '', check_result: '', status: 'active' as const };
const item = (extra: Partial<HuddleItem>): HuddleItem => ({ id: 1, state: 'waiting', wait, ...extra }) as HuddleItem;

describe('waitLine', () => {
  test('says what it waits on and by when', () => {
    expect(waitLine(item({}), NOW, words, 'en-US')).toEqual({ on: 'waiting on staging restart, by today 3:00 pm', check: '', extended: '', asked: false, hold: false });
  });
  test('names the check kind and the extension reason', () => {
    const line = waitLine(item({ wait: { ...wait, check_kind: 'version_live', extended: 1, extend_reason: 'queued behind another' } }), NOW, words, 'en-US');
    expect(line.check).toBe('checks itself: version live');
    expect(line.extended).toBe('extended: queued behind another');
  });
  test('shows the owner question state once escalated', () => {
    expect(waitLine(item({ wait: { ...wait, extended: 1, extend_reason: 'x', status: 'escalated' } }), NOW, words, 'en-US').asked).toBe(true);
  });
  test('a forked parent waiting on its forks says how many still hold it (#1802)', () => {
    const held = item({ wait: undefined, blockers: [{ id: 3, kind: 'children', text: 'its forked tasks', created_by: 'u-1', created_at: 1, holding: 2 }] });
    expect(waitLine(held, NOW, words)).toEqual({ on: 'waiting on its 2 forked tasks', check: '', extended: '', asked: false, hold: true });
    expect(waitLine({ ...held, state: 'open' }, NOW, words).on).toBe('');
  });
  test('draws nothing for a task with no wait, or one no longer waiting', () => {
    expect(waitLine(item({ wait: undefined }), NOW, words).on).toBe('');
    expect(waitLine(item({ state: 'open' }), NOW, words).on).toBe('');
  });
});

describe('waitChip (the collapsed row, Joe (ccsliinc), 2026-10-22, #1710 point 16)', () => {
  const chipStrings = { ...strings, 'cplug.huddle.wait.chip': 'waiting, by {by}', 'cplug.huddle.wait.chip_forks': 'waiting on forks' };
  const chipWords: WaitWords = { ...words, t: (key, params = {}) => Object.entries(params).reduce((text, [k, v]) => text.replace(`{${k}}`, String(v)), chipStrings[key as keyof typeof chipStrings] ?? key) };
  test('a collapsed waiting row says by when', () => {
    expect(waitChip(item({}), NOW, chipWords, 'en-US')).toEqual({ label: 'waiting, by today 3:00 pm', overdue: false, hold: false });
  });
  test('a wait past its expected time reads overdue', () => {
    expect(waitChip(item({}), new Date(2026, 9, 13, 16, 0), chipWords, 'en-US')?.overdue).toBe(true);
  });
  test('a forked parent holding on its forks shows the hold, never a time', () => {
    const held = item({ wait: undefined, blockers: [{ id: 3, kind: 'children', text: 'its forked tasks', created_by: 'u-1', created_at: 1, holding: 2 }] });
    expect(waitChip(held, NOW, chipWords)).toEqual({ label: 'waiting on forks', overdue: false, hold: true });
  });
  test('nothing for a task that is not waiting or has no wait', () => {
    expect(waitChip(item({ state: 'open' }), NOW, chipWords)).toBeNull();
    expect(waitChip(item({ wait: undefined }), NOW, chipWords)).toBeNull();
  });
});
