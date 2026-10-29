import { describe, expect, test } from 'vitest';
import { cronWords } from '../cron-words';
import type { ParseReason } from '../api';
import { HOUR_STEPS, MINUTE_STEPS, REPEATS, buildCron, changeRepeat, checkCron, defaultPick, parsePick, type PickState } from './compose';
import { clockFor } from '../logic/words';
import { cronToWords, createBlockedReason, fireText, parseOutcome } from './words-model';

const PM5: Partial<PickState> = { hour12: 5, ap: 'pm', min: 30 };

describe('pick <-> cron round trips', () => {
  const cases: [string, Partial<PickState>][] = [
    ['daily', { rep: 'daily', ...PM5 }],
    ['days', { rep: 'days', days: [1, 3, 5], ...PM5 }],
    ['days range', { rep: 'days', days: [1, 2, 3, 4, 5] }],
    ['nth', { rep: 'nth', nth: 3, wd: 2, hour12: 5, ap: 'pm', min: 0 }],
    ['monthdate', { rep: 'monthdate', dom: 31, ...PM5 }],
    ['yeardate', { rep: 'yeardate', dom: 4, month: 7, ...PM5 }],
    ['hours', { rep: 'hours', step: 6, min: 15 }],
    ['every hour', { rep: 'hours', step: 1, min: 0 }],
    ['minutes', { rep: 'minutes', step: 20 }],
  ];
  test.each(cases)('%s', (_name, patch) => {
    const state = { ...defaultPick(), ...patch };
    const cron = buildCron(state);
    const back = parsePick(cron);
    expect(back).not.toBeNull();
    expect(buildCron(back as PickState)).toBe(cron);
    expect((back as PickState).rep).toBe(state.rep);
    expect(checkCron(cron)).toEqual({ ok: true });
  });

  test('every repeat option is covered and the repeat menu defaults are valid', () => {
    expect(new Set(cases.map(([, p]) => p.rep))).toEqual(new Set(REPEATS));
    for (const rep of REPEATS) expect(checkCron(buildCron(changeRepeat(defaultPick(), rep)))).toEqual({ ok: true });
    expect(MINUTE_STEPS.every((s) => checkCron(`*/${s} * * * *`).ok)).toBe(true);
    expect(HOUR_STEPS.every((s) => checkCron(`0 */${s} * * *`).ok)).toBe(true);
  });

  test('a cron the picker cannot show stays null, untouched', () => {
    for (const c of ['0 9 1,15 * *', '0 9 * 1-3 *', '*/15 9 * * *', '0 9 * * 1#3,2', 'nonsense']) expect(parsePick(c)).toBeNull();
  });
});

describe('the third tuesday', () => {
  test('the team\'s example reads back as words and round-trips', () => {
    expect(cronToWords('0 17 * * 2#3')).toBe('the third tuesday of every month at 5:00 pm');
    expect(cronWords('0 17 * * 2#3').replace(/\s/g, ' ')).toBe('monthly, third tuesday at 5:00 PM');
    expect(parsePick('0 17 * * tue#3')).toMatchObject({ rep: 'nth', wd: 2, nth: 3, hour12: 5, ap: 'pm' });
    expect(buildCron(parsePick('0 17 * * 2#3') as PickState)).toBe('0 17 * * 2#3');
  });
});

describe('refusals', () => {
  test('# only in the day-of-week field', () => {
    expect(checkCron('0 9 2#3 * *')).toMatchObject({ ok: false, code: 'field_bad' });
    expect(checkCron('0 9 * 1#2 *')).toMatchObject({ ok: false, code: 'field_bad' });
    expect(checkCron('0 9 * * 2#3')).toEqual({ ok: true });
    expect(checkCron('0 9 * * 2#9')).toMatchObject({ ok: false });
  });
  test('the 15 minute floor', () => {
    expect(checkCron('*/10 * * * *')).toEqual({ ok: false, code: 'too_often', text: 'too often: the shortest gap is 15 minutes' });
    expect(checkCron('0,10 9 * * *')).toMatchObject({ code: 'too_often' });
    expect(checkCron('*/15 * * * *')).toEqual({ ok: true });
  });
  test('fields, ranges and a schedule that never fires', () => {
    expect(checkCron('0 9 * *')).toMatchObject({ code: 'fields' });
    expect(checkCron('60 9 * * *')).toMatchObject({ code: 'field_bad', text: 'that is not a schedule: minute is not right' });
    expect(checkCron('0 25 * * *')).toMatchObject({ text: 'that is not a schedule: hour is not right' });
    expect(checkCron('0 9 31 2 *')).toMatchObject({ code: 'never' });
  });
});

describe('the words box result model', () => {
  const fire = { utc: 'u', local: '2026-10-27T17:00:00-04:00', in_zone: '2026-10-27T17:00:00-04:00' };
  test('ok carries the cron, its words and whether the zones differ', () => {
    const ok = parseOutcome({ ok: true, cron: '0 17 * * 2#3', fires: [fire] });
    expect(ok).toMatchObject({ kind: 'ok', cron: '0 17 * * 2#3', differs: false, words: 'the third tuesday of every month at 5:00 pm' });
    const far = parseOutcome({ ok: true, cron: '0 17 * * 2#3', fires: [{ ...fire, in_zone: '2026-10-27T14:00:00-07:00' }] });
    expect(far).toMatchObject({ kind: 'ok', differs: true });
  });
  test('every reason code has its own wording', () => {
    const reasons: ParseReason[] = ['no_ai_connection', 'ai_timeout', 'ai_error', 'ai_output_invalid', 'ai_refused', 'cron_invalid', 'interval_under_15_min', 'never_fires', 'timezone_invalid'];
    const texts = reasons.map((reason) => {
      const out = parseOutcome({ ok: false, reason });
      expect(out).toMatchObject({ kind: 'refused', reason });
      expect((out as { text: string }).text).not.toContain('automations.simple');
      return (out as { text: string }).text;
    });
    expect(new Set(texts).size).toBe(reasons.length);
  });
  test('create is blocked while a result is unconfirmed', () => {
    const ok = parseOutcome({ ok: true, cron: '0 9 * * *', fires: [] });
    expect(createBlockedReason(ok)).toBe('use this schedule or start over before you create.');
    expect(createBlockedReason(null)).toBeNull();
    expect(createBlockedReason(parseOutcome({ ok: false, reason: 'ai_refused' }))).toBeNull();
  });
});

describe('fireText', () => {
  const clock = clockFor('UTC');
  const first = Date.UTC(2026, 9, 16, 9, 0) / 1000;

  test('writes the mockup date and an upper case meridiem, no weekday', () => {
    expect(fireText(clock, first, [first])).toBe('Oct 16, 9:00 AM');
  });

  test('adds the year when the listed fires span more than 300 days', () => {
    const last = first + 400 * 86400;
    expect(fireText(clock, first, [first, last])).toBe('Oct 16 2026, 9:00 AM');
  });
});
