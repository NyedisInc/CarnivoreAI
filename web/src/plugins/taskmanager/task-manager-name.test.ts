import { describe, expect, test } from 'vitest';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { taskManagerTab } from './task-manager-tab';

const CATALOG_EN = enCatalog as Record<string, string>;

describe('huddle shown as swarm', () => {
  test('the dynamic tab label key resolves to "swarm"', () => {
    expect(taskManagerTab.id).toBe('huddle');
    expect(CATALOG_EN[taskManagerTab.labelKey]).toBe('swarm');
  });

  test('the plugin name reads task manager, nav and title read swarm; no visible huddle left in the plugin strings', () => {
    expect(CATALOG_EN['cplug.huddle.name']).toBe('task manager');
    for (const key of ['cplug.huddle.nav', 'cplug.huddle.title']) {
      expect(CATALOG_EN[key]).toBe('swarm');
    }
    const leaks = Object.entries(CATALOG_EN).filter(([k, v]) => k.startsWith('cplug.huddle.') && /huddle/i.test(String(v)));
    expect(leaks).toEqual([]);
  });
});

const OLD_LABEL = /interactive[ -]?to-?do/i;
const ALIAS_FILES = ['lib/plugins-page/screen-host.ts', 'lib/plugins-page/plugin-settings-link.ts', 'lib/menu-page/menu-pages.ts'];

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return sources(full);
    return /\.(ts|svelte|js)$/.test(name) && !/\.test\./.test(name) ? [full] : [];
  });
}

describe('no visible "interactive todo" is left (S6d)', () => {
  test('no shipped i18n catalog value says it', () => {
    const bad = Object.entries(CATALOG_EN).filter(([, v]) => typeof v === 'string' && OLD_LABEL.test(v));
    expect(bad.map(([k]) => k)).toEqual([]);
  });

  test('no Svelte, web or legacy UI source says it, the hash alias files aside', () => {
    const webSrc = resolve(__dirname, '../..');
    const root = resolve(webSrc, '../..');
    const files = [...sources(webSrc), ...sources(join(root, 'client/js')), join(root, 'client/index.html')];
    expect(files.length).toBeGreaterThan(100);
    const bad = files
      .filter((f) => !ALIAS_FILES.some((a) => f.endsWith(a)))
      .filter((f) => OLD_LABEL.test(readFileSync(f, 'utf8')));
    expect(bad).toEqual([]);
  });
});
