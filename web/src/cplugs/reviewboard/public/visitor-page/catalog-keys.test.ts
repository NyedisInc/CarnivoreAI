import { describe, expect, it } from 'vitest';
import catalog from '../../catalog.en.js';
import { LAYER_STRING_NAMES } from './layer-strings';
import { t } from './strings';
import coreSource from '../../../../../../src/cplugs/reviewboard/frame/layer-core.js?raw';
import fieldsSource from '../../../../../../src/cplugs/reviewboard/frame/layer-fields.js?raw';
import moreSource from '../../../../../../src/cplugs/reviewboard/frame/layer-fields-more.js?raw';
import rowsSource from '../../../../../../src/cplugs/reviewboard/frame/layer-rows.js?raw';

const SOURCES = import.meta.glob('./*.{ts,svelte}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const PAGE_FILES = Object.entries(SOURCES).filter(([file]) => !file.endsWith('.test.ts'));
const KEYS = catalog as Record<string, unknown>;
const READ_STATES = ['invalid', 'ended', 'limited', 'misrouted', 'unavailable'];
const POST_STATES = ['malformed', 'rejected', 'has_secret', 'full', 'read_only', 'stale'];
const LIGHTS = ['waiting', 'saved', 'failed'];

describe('the visitor page\'s strings', () => {
  it('finds the page files (the sweep is not looking at nothing)', () => {
    expect(PAGE_FILES.length).toBeGreaterThan(8);
  });

  it('has every literal key it names in the catalog', () => {
    const missing: string[] = [];
    for (const [file, source] of PAGE_FILES) {
      for (const [, key] of source.matchAll(/'(cplug\.reviewboard\.public\.[a-z0-9_.]*[a-z0-9_])'/g)) {
        if (typeof KEYS[key!] !== 'string') missing.push(`${file}: ${key}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it('has a sentence for every state a read or a post can show and every autosave light', () => {
    const wanted = [
      ...READ_STATES.map((s) => `cplug.reviewboard.public.page.state.${s}`), ...POST_STATES.map((s) => `cplug.reviewboard.public.page.post.${s}`),
      ...LIGHTS.map((l) => `cplug.reviewboard.public.page.save.${l}`),
    ];
    expect(wanted.filter((key) => t(key) === key)).toEqual([]);
  });

  it('builds no template key outside the three families this sweep lists', () => {
    const families = new Set<string>();
    for (const [, source] of PAGE_FILES) for (const [, family] of source.matchAll(/`(cplug\.reviewboard\.public\.[a-z0-9_.]+)\.\$\{/g)) families.add(family!);
    expect([...families].sort()).toEqual(['cplug.reviewboard.public.page.post', 'cplug.reviewboard.public.page.save', 'cplug.reviewboard.public.page.state']);
  });
});

describe('the strings the layer in the frame asks for', () => {
  it('are all sent, each from a catalog key of this plugin', () => {
    const asked = new Set<string>();
    for (const source of [coreSource, fieldsSource, moreSource, rowsSource]) {
      for (const [, name] of source.matchAll(/cplug\.reviewboard\.layer\.([a-z0-9_]+)/g)) asked.add(name!);
      for (const [, name] of source.matchAll(/\bstr\('([a-z0-9_]+)'/g)) asked.add(name!);
    }
    expect(asked.size).toBeGreaterThan(0);
    expect([...asked].filter((name) => !(LAYER_STRING_NAMES as readonly string[]).includes(name))).toEqual([]);
    expect(LAYER_STRING_NAMES.filter((name) => typeof KEYS[`cplug.reviewboard.public.layer.${name}`] !== 'string')).toEqual([]);
  });
});
