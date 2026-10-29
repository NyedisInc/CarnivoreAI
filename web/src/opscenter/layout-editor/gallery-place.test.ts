import { describe, expect, test } from 'vitest';
import { META } from '../engine/meta';
import { resetLayout } from '../engine/model';
import { galleryTarget } from './gallery-place';

const home = () => resetLayout(META, 'home');

describe('galleryTarget', () => {
  test('no focus, or a focus that is not on the surface, puts the widget in a row of its own at the end', () => {
    const layout = home();
    const last = layout.rows.at(-1)!;
    const end = { kind: 'new', after: last.id };
    expect(galleryTarget(layout, 'analytics:x', null, 'panel')).toEqual(end);
    expect(galleryTarget(layout, 'analytics:x', 'analytics:gone', 'tile')).toEqual(end);
    expect(galleryTarget(layout, 'analytics:x', 'analytics:x', 'full')).toEqual(end);
  });

  test('when the widget already sits alone in the last row there is nothing to move', () => {
    const layout = home();
    const alone = { ...layout, rows: [...layout.rows.slice(0, -1), { ...layout.rows.at(-1)!, slots: [{ id: 'analytics:x' as const, fr: 1 }] }] };
    expect(galleryTarget(alone, 'analytics:x', null, 'panel')).toBeNull();
  });

  test('a panel card lands right of the focused cell, a full card in a row of its own after that row', () => {
    const layout = home();
    const row = layout.rows.find((one) => one.slots.length > 1)!;
    const focus = row.slots[0]!.id;
    expect(galleryTarget(layout, 'analytics:x', focus, 'tile')).toEqual({ kind: 'row', row: row.id, index: 1 });
    expect(galleryTarget(layout, 'analytics:x', focus, 'full')).toEqual({ kind: 'new', after: row.id });
  });
});
