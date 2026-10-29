
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { leavesOf, terminalSlotsOf, withoutSlot } from './tree';
import type { LayoutV7 } from './types';

/** Where the shared fixture lives, from this file. */
const FIXTURE = fileURLToPath(new URL('../../../../../tests/fixtures/layout_v7_parity.json', import.meta.url));

interface ParityCase {
  name: string;
  v6: unknown;
  v7: LayoutV7;
  terminalSlots: string[];
  drops: { slot: string; v7: LayoutV7 }[];
}

interface ParityFile {
  about: string;
  cases: ParityCase[];
}

function build(stored: ParityFile): ParityFile {
  return {
    about: stored.about,
    cases: stored.cases.map(({ name, v6, v7 }) =>
      JSON.parse(
        JSON.stringify({
          name,
          v6,
          v7,
          terminalSlots: terminalSlotsOf(v7),
          drops: leavesOf(v7.variants.wide.root).map((one) => ({ slot: one, v7: withoutSlot(v7, one, 'terminal') })),
        }),
      ),
    ),
  };
}

describe('the python parity fixture', () => {
  it('matches what the engine computes', () => {
    const stored = JSON.parse(readFileSync(FIXTURE, 'utf8')) as ParityFile;
    const now = build(stored);
    if (process.env['UPDATE_V7_PARITY'] === '1') writeFileSync(FIXTURE, `${JSON.stringify(now)}\n`);
    expect(stored).toEqual(now);
  });
});
