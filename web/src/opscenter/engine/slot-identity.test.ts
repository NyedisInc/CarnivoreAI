import { expect, test } from 'vitest';
import {
  rekeyArrangement, rekeyEntry, rowIdOfSlot, sessionForSlot, slotForSession, slotNameFor, slotRenames,
} from './slot-identity';
import { PRIMARY_SLOT, resetLayout, addInstance, instancesOf } from './model';
import { META } from './meta';
import type { Layout } from './types';

const live = (id: string, row: number | null) => ({ session: { id }, session_row_id: row });

function grid(...names: string[]): Layout {
  let layout = resetLayout(META, 'terminal');
  for (const name of names) layout = addInstance(layout, 'terminal', name, '', META).layout;
  return layout;
}

test('a row-keyed slot resolves to the app id its row holds now, else to its own tail', () => {
  expect(rowIdOfSlot('terminal:row:7')).toBe(7);
  expect(rowIdOfSlot('terminal:ses_7')).toBeNull();
  expect(rowIdOfSlot('terminal:row:x')).toBeNull();
  expect(sessionForSlot('terminal:row:7', [live('ses_old', 3), live('ses_new', 7)])).toBe('ses_new');
  expect(sessionForSlot('terminal:row:7', [live('ses_old', 3)])).toBe('row:7');
  expect(sessionForSlot('terminal:row:7', null)).toBe('row:7');
  expect(sessionForSlot('terminal:ses_a', [live('ses_a', 7)])).toBe('ses_a');
  expect(sessionForSlot(PRIMARY_SLOT, [live('ses_a', 7)])).toBe('');
});

test('a session is minted onto its row, or onto its app id when the listing carries no row', () => {
  const rows = [live('ses_a', 7), live('adopted:cloude_x', null)];
  expect(slotForSession('ses_a', rows)).toBe('terminal:row:7');
  expect(slotNameFor('ses_a', rows)).toBe('row:7');
  expect(slotForSession('adopted:cloude_x', rows)).toBe('terminal:adopted:cloude_x');
  expect(slotForSession('ses_new', rows)).toBe('terminal:ses_new');
  expect(slotForSession('ses_a', null)).toBe('terminal:ses_a');
  expect(/^terminal:[A-Za-z0-9@._:-]{1,120}$/.test(slotForSession('ses_a', rows))).toBe(true);
});

test('renames: live with a row is renamed, rowless is kept, not live is dropped only when told to', () => {
  const rows = [live('ses_a', 7), live('ses_x', null)];
  const ids = ['terminal:ses_a', 'terminal:ses_x', 'terminal:ses_gone', PRIMARY_SLOT, 'terminal:row:9', 'hero'];
  expect([...slotRenames(ids, rows, false)]).toEqual([['terminal:ses_a', 'terminal:row:7']]);
  expect([...slotRenames(ids, rows, true)]).toEqual([
    ['terminal:ses_a', 'terminal:row:7'],
    ['terminal:ses_gone', null],
  ]);
  expect([...slotRenames(['terminal:ses_a', 'terminal:row:7'], rows, false)]).toEqual([['terminal:ses_a', null]]);
});

test('re-key an entry: grid slots, group keys, tabs and active tabs move together', () => {
  const layout = grid('ses_a', 'ses_gone');
  const groups = {
    [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, 'terminal:ses_b'] },
    'terminal:ses_a': { tabs: ['terminal:ses_a', 'terminal:ses_c'] },
  };
  const active = { [PRIMARY_SLOT]: 'terminal:ses_b', 'terminal:ses_a': 'terminal:ses_c' };
  const rows = [live('ses_a', 1), live('ses_b', 2), live('ses_c', 3)];

  const result = rekeyEntry({ layout, groups, active }, rows, true);

  expect(result.changed).toBe(true);
  expect(result.dropped).toBe(1);
  expect(instancesOf(result.layout!)).toEqual([PRIMARY_SLOT, 'terminal:row:1']);
  expect(result.groups).toEqual({
    [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, 'terminal:row:2'] },
    'terminal:row:1': { tabs: ['terminal:row:1', 'terminal:row:3'] },
  });
  expect(result.active).toEqual({ [PRIMARY_SLOT]: 'terminal:row:2', 'terminal:row:1': 'terminal:row:3' });
  expect(instancesOf(layout)).toEqual([PRIMARY_SLOT, 'terminal:ses_a', 'terminal:ses_gone']);
});

test('a component lives while any of its tabs does, under its old name when that name cannot be mapped', () => {
  const layout = grid('ses_dead', 'ses_lone');
  const groups = { 'terminal:ses_dead': { tabs: ['terminal:ses_dead', 'terminal:ses_b'] } };
  const result = rekeyEntry({ layout, groups, active: { 'terminal:ses_dead': 'terminal:ses_dead' } }, [live('ses_b', 2)], true);
  expect(instancesOf(result.layout!)).toEqual([PRIMARY_SLOT, 'terminal:ses_dead']);
  expect(result.groups).toEqual({ 'terminal:ses_dead': { tabs: ['terminal:row:2'] } });
  expect(result.active).toEqual({});
});

test('without the drop, a slot naming no live session is left exactly as it was', () => {
  const layout = grid('ses_gone');
  const entry = { layout, groups: {}, active: {} };
  const result = rekeyEntry(entry, [live('ses_a', 1)], false);
  expect(result.changed).toBe(false);
  expect(result.layout).toBe(layout);
});

test('the synced map: the same object back when nothing moved, and an unreadable entry kept as sent', () => {
  const clean = { v: 1 as const, sessions: { k: { layout: grid('row:1'), groups: {} } } };
  expect(rekeyArrangement(clean, [live('ses_a', 1)], true).map).toBe(clean);

  const broken = { rows: 'nonsense' } as unknown as Layout;
  const map = {
    v: 1 as const,
    sessions: {
      bad: { layout: broken, groups: { 'terminal:ses_a': { tabs: ['terminal:ses_a'] } } },
      good: { layout: grid('ses_a'), groups: {} },
    },
  };
  const { map: next, dropped } = rekeyArrangement(map, [live('ses_a', 1)], true);
  expect(dropped).toBe(0);
  expect(next.sessions.bad).toBe(map.sessions.bad);
  expect(instancesOf(next.sessions.good!.layout!)).toEqual([PRIMARY_SLOT, 'terminal:row:1']);
});
