import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';

const catalog = readFileSync(new URL('../../../../../client/js/i18n/catalog.en.js', import.meta.url), 'utf8');
const keys = [...catalog.matchAll(/^\s*'([a-z0-9_.]+)':/gm)].map((m) => m[1]!);

test('every t() key in the analytics live-line files is a catalog key, whatever the quote style', () => {
  let seen = 0;
  for (const file of ['Controls.svelte', 'TimelineView.svelte']) {
    const source = readFileSync(new URL(`./${file}`, import.meta.url), 'utf8');
    for (const match of source.matchAll(/\bt\(\s*(['"`])([^'"`]+)\1/g)) {
      seen += 1;
      const key = match[2]!;
      if (key.includes('${')) {
        const prefix = key.slice(0, key.indexOf('${'));
        expect(keys.some((k) => k.startsWith(prefix)), `${file} builds ${key}`).toBe(true);
      } else {
        expect(keys, `${file} uses ${key}`).toContain(key);
      }
    }
  }
  expect(seen).toBeGreaterThan(10);
});
