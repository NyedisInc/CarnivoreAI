import { describe, expect, test } from 'vitest';
import type { HuddleItem } from '../huddle-model';
import { MK2_CHIPS_FULL_FROM_PX, MK2_CHIPS_ICON_BELOW_PX, MK2_CHIP_ICON, MK2_CHIP_ORDER, MK2_CHIP_TEST, chipCount, chipMode } from './mk2-chips';

describe('chipMode', () => {
  test('the three looks at their widths, the edges included', () => {
    expect(chipMode(MK2_CHIPS_FULL_FROM_PX)).toBe('full');
    expect(chipMode(MK2_CHIPS_FULL_FROM_PX - 1)).toBe('count');
    expect(chipMode(MK2_CHIPS_ICON_BELOW_PX)).toBe('count');
    expect(chipMode(MK2_CHIPS_ICON_BELOW_PX - 1)).toBe('icon');
  });

  test('the row never wraps for a count: a width that shows words or counts is wide enough for the widest counts (#1710 round 7 part 1)', () => {
    expect(chipMode(320)).toBe('count');
    expect(chipMode(340)).toBe('count');
    expect(MK2_CHIPS_FULL_FROM_PX).toBe(363);
    expect(MK2_CHIPS_ICON_BELOW_PX).toBe(249);
  });

  test('an unmeasured width is the full look, never a smaller guess', () => {
    expect(chipMode(0)).toBe('full');
    expect(chipMode(Number.NaN)).toBe('full');
  });

  test('every chip has an icon', () => {
    expect(MK2_CHIP_ORDER.every((id) => !!MK2_CHIP_ICON[id])).toBe(true);
  });
});

describe('scheduled chip (#2982)', () => {
  const task = (id: number, status: string, trigger: Record<string, unknown> | null): HuddleItem =>
    ({ id, status, thread: [], start_trigger: trigger } as unknown as HuddleItem);
  const at = { fire_at: 1_900_000_000, fired_at: null, last_error: null };
  const repeat = { freq: 'daily', time: '09:00' };

  test('counts and filters every task with a run still coming, whatever its section', () => {
    const counted = [task(1, 'review', { ...at, repeat }), task(2, 'working', { ...at })];
    const skipped = [
      task(3, 'working', { ...at, fired_at: 1_800_000_000 }),
      task(4, 'review', { ...at, repeat, paused: true }),
      task(5, 'done', { ...at, repeat }),
      task(6, 'open', null),
    ];
    const items = [...counted, ...skipped];
    expect(chipCount('scheduled', items)).toBe(2);
    expect(items.filter(MK2_CHIP_TEST.scheduled).map((i) => i.id)).toEqual([1, 2]);
  });

  test('a one-time task that never fired counts even when the server leaves fired_at out', () => {
    const never = task(7, 'working', { kind: 'at', fire_at_iso: '2026-11-24T10:00:00-05:00' });
    const failed = task(8, 'question', { kind: 'at', fire_at_iso: '2026-11-13T09:00:00-05:00', fired_at: 1_794_000_000, last_error: 'not sent' });
    expect([never, failed].filter(MK2_CHIP_TEST.scheduled).map((i) => i.id)).toEqual([7]);
  });
});
