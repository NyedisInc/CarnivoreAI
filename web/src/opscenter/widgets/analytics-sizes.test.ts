
import { describe, expect, test } from 'vitest';
import { FIT_TOLERANCE_PX, SIZE_UNIT_PX } from './fits';
import { FIT_DECLARATIONS } from './fit-declarations';
import { namedSize } from './named-sizes';
import { VIZ_KINDS, VIZ_SPECS } from '../viz/specs';

const CHROME_PX = 40;

describe('core.analytics declared sizes', () => {
  test.each(FIT_DECLARATIONS.analytics.sizes)('%s holds every renderer above its own floor', (name) => {
    const size = namedSize(name);
    const width = size.w * SIZE_UNIT_PX.w;
    const height = size.h * SIZE_UNIT_PX.h - CHROME_PX;
    for (const kind of VIZ_KINDS) {
      const min = VIZ_SPECS[kind].min;
      expect(width + FIT_TOLERANCE_PX, `${kind} width at ${name}`).toBeGreaterThanOrEqual(min.width);
      expect(height + FIT_TOLERANCE_PX, `${kind} height at ${name}`).toBeGreaterThanOrEqual(min.height);
    }
  });
});
