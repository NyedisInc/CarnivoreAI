import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';
import order from '../../../src/cplugs/order.json';
import { BUILTIN_CPLUGS, SHIP_ORDER } from './builtin';
import { POPOUT_CPLUGS } from './popout';

const read = (name: string): string => readFileSync(new URL(name, import.meta.url), 'utf8');

describe('one ship order', () => {
  test('the order the web uses is the server file, in the server file order', () => {
    expect([...SHIP_ORDER]).toEqual(order.order);
    const ids = BUILTIN_CPLUGS.map((c) => c.id);
    const hinted = order.order.filter((id) => ids.includes(id));
    expect(ids.slice(0, hinted.length)).toEqual(hinted);
  });

  test('neither ship list file carries a literal order array', () => {
    expect(read('./builtin.ts')).not.toMatch(/\['huddle'/);
    expect(read('./popout.ts')).not.toMatch(/\['huddle'/);
  });

  test('the pop-out list follows the same order', () => {
    const ids = POPOUT_CPLUGS.map((c) => c.id);
    const rank = (id: string): number => { const i = order.order.indexOf(id); return i < 0 ? order.order.length : i; };
    expect(ids).toEqual([...ids].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b)));
  });
});
