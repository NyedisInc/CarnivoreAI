import { describe, expect, test } from 'vitest';
import { HEAD_ROW_PX, PHONE_HEAD_PX, headParts, headerShown, type HeadPart } from './widget-head';
import { META, TERMINAL_META, BROWSER_META, ANALYTICS_META } from '../engine/meta';
import { resetLayout } from '../engine/model';
import { validate } from '../engine/persist';
import { validateV7 } from '../engine/v7/validate';
import { v7Layout } from '../engine/v7/fixtures/v7-layouts';
import { toV6 } from '../engine/v7/adapt';

function words(parts: HeadPart[]): string[] {
  return parts.map((part) => (part.kind === 'group' ? `g${part.at}` : part.kind));
}

describe('the separator rule: the header draws them, between non-empty groups and before the close x', () => {
  test.each<[string, boolean[], boolean, string[]]>([
    ['nothing at all', [], false, []],
    ['the close x alone takes no leading separator', [], true, ['close']],
    ['one group and no close: no trailing separator', [true], false, ['g0']],
    ['one group and the close', [true], true, ['g0', 'sep', 'close']],
    ['two groups and the close', [true, true], true, ['g0', 'sep', 'g1', 'sep', 'close']],
    ['an empty group between two never doubles a separator', [true, false, true], true, ['g0', 'sep', 'g2', 'sep', 'close']],
    ['empty groups at either end never lead or trail', [false, true, false], false, ['g1']],
    ['every group empty, close drawn', [false, false], true, ['close']],
  ])('%s', (_name, groups, closable, expected) => {
    expect(words(headParts(groups, closable))).toEqual(expected);
  });

  test('a separator never starts, ends or doubles, over every pattern of four groups', () => {
    for (let mask = 0; mask < 32; mask += 1) {
      const groups = [0, 1, 2, 3].map((bit) => (mask & (1 << bit)) !== 0);
      const closable = (mask & 16) !== 0;
      const drawn = words(headParts(groups, closable));
      expect(drawn[0]).not.toBe('sep');
      expect(drawn[drawn.length - 1]).not.toBe('sep');
      drawn.forEach((word, at) => {
        if (word === 'sep') expect(drawn[at + 1]).not.toBe('sep');
      });
      expect(drawn.filter((word) => word.startsWith('g')).length).toBe(groups.filter(Boolean).length);
    }
  });
});

describe('the show header tick default, per surface', () => {
  test('a grid copy, a drawer card and a pop-out start on; a widget bar slide-out starts off (Alex, 2026-10-11)', () => {
    expect(headerShown('grid', undefined)).toBe(true);
    expect(headerShown('drawer', undefined)).toBe(true);
    expect(headerShown('popout', undefined)).toBe(true);
    expect(headerShown('rail', undefined)).toBe(false);
  });

  test('the copy own tick wins over the default either way', () => {
    expect(headerShown('rail', true)).toBe(true);
    expect(headerShown('grid', false)).toBe(false);
  });
});

describe('one height and the override flags', () => {
  test('every card widget record declares the one header height; the phone row stays 44px', () => {
    expect(HEAD_ROW_PX).toBe(31);
    expect(PHONE_HEAD_PX).toBe(44);
    for (const meta of [...Object.values(META), TERMINAL_META, BROWSER_META, ANALYTICS_META]) {
      if (meta.chrome === 'card') expect(meta.titleHeight, meta.id).toBe(HEAD_ROW_PX);
    }
  });

  test('only the terminal records keep their own head and draw no close x', () => {
    expect(TERMINAL_META.ownHead).toBe(true);
    expect(TERMINAL_META.closable).toBe(false);
    for (const meta of [...Object.values(META), BROWSER_META, ANALYTICS_META]) {
      expect(meta.ownHead ?? false, meta.id).toBe(false);
      expect(meta.closable ?? true, meta.id).toBe(true);
    }
  });
});

describe('the tick is stored per copy in the synced layout', () => {
  test('a stored layout keeps its ticked-off copies, drops a non-slot as a repair, and reads unchanged without the list', () => {
    const base = resetLayout(META, 'home');
    expect(validate(base, META, 'home').layout?.headerOff).toBeUndefined();
    const kept = validate({ ...base, headerOff: ['running-sessions'] }, META, 'home');
    expect(kept.layout?.headerOff).toEqual(['running-sessions']);
    expect(kept.repaired).toBe(false);
    const repaired = validate({ ...base, headerOff: ['running-sessions', 'no such cell', 'running-sessions'] }, META, 'home');
    expect(repaired.layout?.headerOff).toEqual(['running-sessions']);
    expect(repaired.repaired).toBe(true);
  });

  test('the v7 tree carries the list both ways and refuses a malformed one by name', () => {
    const tree = v7Layout('terminalHeaderOff');
    expect(tree.headerOff).toEqual(['terminal:@primary']);
    expect(validateV7(tree, 'terminal').ok).toBe(true);
    expect(toV6(tree, 'terminal').layout.headerOff).toEqual(['terminal:@primary']);
    const bad = validateV7({ ...tree, headerOff: 'terminal:@primary' }, 'terminal');
    expect(bad.ok ? null : bad.refusal).toBe('header-off');
  });
});
