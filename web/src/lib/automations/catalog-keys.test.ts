import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const KEY_RE = /['"`](automations\.page\.[a-z0-9_.]*[a-z0-9_])['"`]/g;

function sources(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) return sources(full);
    return /\.(svelte|ts)$/.test(e.name) && !/\.test\.ts$/.test(e.name) ? [full] : [];
  });
}

describe('automations page catalog keys', () => {
  test('every referenced static key exists', () => {
    const catalog = enCatalog as Record<string, string>;
    const missing: string[] = [];
    let seen = 0;
    for (const file of sources(HERE)) {
      for (const m of fs.readFileSync(file, 'utf8').matchAll(KEY_RE)) {
        const key = m[1];
        if (key === undefined) continue;
        seen++;
        if (!(key in catalog) && !(`${key}_one` in catalog && `${key}_many` in catalog)) missing.push(`${path.relative(HERE, file)}: ${key}`);
      }
    }
    expect(seen).toBeGreaterThan(50);
    expect(missing).toEqual([]);
  });
});
