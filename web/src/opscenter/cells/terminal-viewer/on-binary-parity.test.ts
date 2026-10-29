import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, test } from 'vitest';

const ROOT = ((): string => {
  for (const base of ['.', '..', '../..']) {
    const candidate = path.resolve(process.cwd(), base);
    if (
      existsSync(path.join(candidate, 'web/src/opscenter/lib/input-focus.svelte.ts')) &&
      existsSync(path.join(candidate, 'client/js/terminal-input-kind.js'))
    ) {
      return candidate;
    }
  }
  throw new Error('repository root not found from ' + process.cwd());
})();

const TREES: ReadonlyArray<{ name: string; dir: string; extensions: string[] }> = [
  { name: 'web/src (compiled)', dir: 'web/src', extensions: ['.ts', '.svelte'] },
  { name: 'client/js (vanilla)', dir: 'client/js', extensions: ['.js'] },
];

function filesUnder(dir: string, extensions: string[]): string[] {
  const out: string[] = [];
  const walk = (at: string): void => {
    for (const entry of readdirSync(at)) {
      const full = path.join(at, entry);
      if (statSync(full).isDirectory()) {
        walk(full);
        continue;
      }
      if (extensions.some((ext) => entry.endsWith(ext))) out.push(full);
    }
  };
  walk(dir);
  return out;
}

const WIRED = /\bonBinary\s*\(/;

const CONTROL = /\bonData\s*\(/;

describe('the binary input channel is wired in neither tree', () => {
  for (const tree of TREES) {
    test(`${tree.name} attaches nothing to onBinary`, () => {
      const files = filesUnder(path.join(ROOT, tree.dir), tree.extensions);

      expect(files.length).toBeGreaterThan(0);
      const wiresOnData = files.filter((file) => CONTROL.test(readFileSync(file, 'utf8')));
      expect(
        wiresOnData.length,
        `${tree.name} wires onData nowhere, so this walk is reading the wrong files`,
      ).toBeGreaterThan(0);

      const offenders = files
        .filter((file) => WIRED.test(readFileSync(file, 'utf8')))
        .map((file) => path.relative(ROOT, file));
      expect(
        offenders,
        'onBinary is wired in ' +
          tree.name +
          '. Both trees deliberately leave xterm`s binary channel unattached, ' +
          'so X10-encoded mouse reports are dropped for the grid cells and the ' +
          'main terminal alike. Wiring it in one tree alone makes the two ' +
          'surfaces send different bytes for the same gesture, and the new ' +
          'channel would bypass the owner-only gate that sits on onData. ' +
          'Offenders: ' +
          offenders.join(', '),
      ).toEqual([]);
    });
  }
});
