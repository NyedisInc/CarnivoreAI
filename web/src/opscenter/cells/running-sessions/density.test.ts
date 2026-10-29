import { describe, expect, test } from 'vitest';

import { DENSITY_OPTION, densityOf, nameLines } from './density';
import { isRepeatable, setItemOption, type ZoneItem } from '../../../lib/drawer-zone/zone-model';
import { hasPlacementOptions } from '../../widgets/placement-options';

describe('densityOf and nameLines', () => {
  test('normal is the default and takes two lines where the host stores a choice', () => {
    expect(densityOf(undefined)).toBe('normal');
    expect(densityOf({})).toBe('normal');
    expect(nameLines({}, true)).toBe(2);
  });

  test('compact takes one line, and an unknown stored value falls back to normal', () => {
    expect(densityOf({ [DENSITY_OPTION]: 'compact' })).toBe('compact');
    expect(nameLines({ [DENSITY_OPTION]: 'compact' }, true)).toBe(1);
    expect(densityOf({ [DENSITY_OPTION]: 'cozy' })).toBe('normal');
  });

  test('a host that stores no options keeps one line whatever was stored', () => {
    expect(nameLines({}, false)).toBe(1);
    expect(nameLines({ [DENSITY_OPTION]: 'normal' }, false)).toBe(1);
  });
});

describe('the choice is stored on the placement and the widget stays single copy', () => {
  test('the widget keeps placement options but is not repeatable', () => {
    expect(hasPlacementOptions('core.running-sessions')).toBe(true);
    expect(isRepeatable('core.running-sessions')).toBe(false);
  });

  test('setItemOption stores and clears the density on the one placement', () => {
    const items: ZoneItem[] = [{ widget: 'core.running-sessions', look: null }];
    const stored = setItemOption(items, 'core.running-sessions', DENSITY_OPTION, 'compact');
    expect(stored[0]?.options).toEqual({ [DENSITY_OPTION]: 'compact' });
    expect(setItemOption(stored, 'core.running-sessions', DENSITY_OPTION, null)[0]?.options).toBeUndefined();
  });
});
