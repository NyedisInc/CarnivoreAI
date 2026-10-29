import { describe, expect, it } from 'vitest';
import { newestFirst } from './activity-order';
import type { ActivityEntry } from './activity.svelte';

function line(id: string, at: number, time: string): ActivityEntry {
  return { id, at, time, tag: 'system', message: id, source: '' };
}

describe('newestFirst', () => {
  it('puts 00:05 (today) above 23:58 (yesterday)', () => {
    const out = newestFirst([line('old', 1000, '23:58:00'), line('new', 2000, '00:05:00')]);
    expect(out.map((l) => l.id)).toEqual(['new', 'old']);
  });
  it('breaks a same-millisecond tie by store position, later is newer', () => {
    const out = newestFirst([line('a', 5, '10:00:00'), line('b', 5, '10:00:00')]);
    expect(out.map((l) => l.id)).toEqual(['b', 'a']);
  });
});
