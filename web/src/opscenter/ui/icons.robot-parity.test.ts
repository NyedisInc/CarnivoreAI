import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import { icons, type SizedIcon } from './icons';

const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url));

function legacySessionModelIcon(): { ROBOT: string } {
  const context: Record<string, unknown> = { console, window: {} };
  vm.createContext(context);
  const src = fs.readFileSync(
    path.join(repoRoot, 'client', 'js', 'session-model-icon.js'),
    'utf8',
  );
  vm.runInContext(src, context);
  return (context['window'] as Record<string, unknown>)['SessionModelIcon'] as {
    ROBOT: string;
  };
}

describe('the tab strip robot matches the legacy model-mark robot', () => {
  test('client/js/session-model-icon.js loads and exports ROBOT in a bare sandbox', () => {
    const legacy = legacySessionModelIcon();
    expect(typeof legacy.ROBOT).toBe('string');
    expect(legacy.ROBOT.length).toBeGreaterThan(0);
  });

  test('icons.ts "bot" is byte-identical to the legacy ROBOT, on its own 20x20 viewBox', () => {
    const legacy = legacySessionModelIcon();
    const bot = icons['bot'];
    expect(typeof bot).not.toBe('string');
    const sized = bot as SizedIcon;
    expect(sized.path).toBe(legacy.ROBOT);
    expect(sized.viewBox).toBe('0 0 20 20');
  });
});
