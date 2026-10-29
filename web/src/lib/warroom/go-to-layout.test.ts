import { describe, expect, it } from 'vitest';
import { layoutChoice } from './go-to-layout';

const L = (uuid: string, name: string, rows: number[]) => ({
  layout_uuid: uuid,
  name,
  members: rows.map((r) => ({ session_row_id: r, session_uuid: `s${r}` })),
});

describe('layoutChoice', () => {
  it('is none for a session in no layout, an unknown row, or an empty list', () => {
    expect(layoutChoice(7, [L('a', 'one', [1])]).kind).toBe('none');
    expect(layoutChoice(null, [L('a', 'one', [7])]).kind).toBe('none');
    expect(layoutChoice(7, []).kind).toBe('none');
  });

  it('is one with the layout and the session uuid for a single membership', () => {
    const got = layoutChoice(7, [L('a', 'one', [7]), L('b', 'two', [1])]);
    expect(got.kind).toBe('one');
    expect(got.layouts).toEqual([{ uuid: 'a', name: 'one' }]);
    expect(got.sessionUuid).toBe('s7');
  });

  it('is many, in the given order, for several memberships', () => {
    const got = layoutChoice(7, [L('a', 'one', [7]), L('b', 'two', [7, 2])]);
    expect(got.kind).toBe('many');
    expect(got.layouts.map((l) => l.uuid)).toEqual(['a', 'b']);
  });
});
