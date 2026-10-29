import { describe, expect, it } from 'vitest';
import { META } from '../engine/meta';
import { WARROOM_ROW } from './rail-items';

describe('war room icon', () => {
  it('the menu row and the widget title strip read the same icon', () => {
    expect(WARROOM_ROW.icon).toBe(META.warroom.icon);
    expect(META.warroom.icon).toBe('terminal');
  });
});
