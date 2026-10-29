import { describe, expect, test } from 'vitest';
import { ANALYTICS_META, BROWSER_META, CELL_IDS, META, TERMINAL_META } from '../engine/meta';
import type { CellMeta } from '../engine/types';
import { pickState } from '../lib/states';
import { CORE_MANIFESTS, coreWidgetId, manifestForSlot } from './core-manifests';
import { resolveDensity } from './density';
import { validateManifest } from './validate';
import { WIDGET_TYPES } from './types';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';

const PAIRS: [string, CellMeta][] = [
  ...CELL_IDS.map((id): [string, CellMeta] => [coreWidgetId(id), META[id]]),
  [coreWidgetId('terminal'), TERMINAL_META],
  [coreWidgetId('browser'), BROWSER_META],
  [coreWidgetId('analytics'), ANALYTICS_META],
];

describe('core manifests', () => {
  test('there is exactly one manifest per cell and per instance kind', () => {
    expect(CELL_IDS).toHaveLength(39);
    expect(Object.keys(CORE_MANIFESTS).sort()).toEqual(PAIRS.map(([id]) => id).sort());
  });

  test.each(PAIRS)('%s passes the validator', (id) => {
    const check = validateManifest(CORE_MANIFESTS[id]);
    expect(check.ok ? 'ok' : `${check.refusal}: ${check.detail}`).toBe('ok');
  });

  test.each(PAIRS)('%s reads its record rather than copying it', (id, meta) => {
    const manifest = CORE_MANIFESTS[id]!;
    expect(manifest.titleKey).toBe(meta.titleKey);
    expect(manifest.icon).toBe(meta.icon);
    expect(manifest.iconTone).toBe(meta.iconTone);
    expect(manifest.bounds).toEqual({ minW: meta.minPx, minH: meta.minHeight });
    expect(manifest.densities.width).toBe(meta.widthStates);
    expect(manifest.densities.height).toBe(meta.heightStates);
  });

  test.each(PAIRS)('%s resolves density exactly as CellHost picks its states', (id, meta) => {
    const manifest = CORE_MANIFESTS[id]!;
    for (const width of [0, 179, 180, 371, 372, 559, 560, 1080, 2000]) {
      for (const height of [0, 43, 44, 119, 120, 200, 900]) {
        expect(resolveDensity(manifest.densities, { width, height })).toEqual({
          width: pickState(meta.widthStates, width),
          height: pickState(meta.heightStates, height),
        });
      }
    }
  });

  test('singletons are singleton and instance kinds are per-target', () => {
    for (const id of CELL_IDS) expect(CORE_MANIFESTS[coreWidgetId(id)]!.instancing).toBe('singleton');
    expect(CORE_MANIFESTS['core.terminal']!.instancing).toBe('per-target');
    expect(CORE_MANIFESTS['core.browser']!.instancing).toBe('per-target');
    expect(CORE_MANIFESTS['core.analytics']!.instancing).toBe('per-target');
  });

  test('canvases follow each page default: the hidden-by-default cells reach the terminal page, the rest are home only', () => {
    for (const id of CELL_IDS) {
      const expected = id === 'notes' || id === 'files' || id === 'scheduled-tasks' || id === 'keep-awake' || id === 'machine-stats' || id === 'changes' || id === 'task-manager' || id === 'task-manager-all' || id === 'task-manager-mk2' || id === 'task-manager-mk2-all' || id === 'crosstalk' || id === 'tasks' || id === 'tasks-all' || id === 'bookmarks' || id === 'bookmarks-all' || id === 'pipeline' || id === 'developer' || id === 'automations' || id === 'automations-all' || id === 'session-contents' || id === 'warroom' || id === 'shell' || id === 'timeline' || id === 'questions' || id === 'task-list' || id === 'projects' ? ['home', 'terminal'] : ['home'];
      expect(CORE_MANIFESTS[coreWidgetId(id)]!.canvases).toEqual(expected);
    }
    expect(CORE_MANIFESTS['core.terminal']!.canvases).toEqual(['home', 'terminal']);
    expect(CORE_MANIFESTS['core.analytics']!.canvases).toEqual(['home', 'terminal']);
  });

  test('every widget declares a type label the string catalog names (the drawer tag, issue #1157)', () => {
    const catalog = enCatalog as Record<string, string>;
    for (const manifest of Object.values(CORE_MANIFESTS)) {
      expect(WIDGET_TYPES, manifest.id).toContain(manifest.type);
      expect(catalog[`widgets.type.${manifest.type}`], manifest.id).toBeTypeOf('string');
    }
    for (const type of WIDGET_TYPES) expect(catalog[`widgets.type.${type}`], type).toBeTypeOf('string');
  });

  test('only the widgets that own a live connection declare keepAlive host', () => {
    const kept = Object.values(CORE_MANIFESTS).filter((m) => m.keepAlive === 'host').map((m) => m.id);
    expect(kept.sort()).toEqual(['core.browser', 'core.terminal']);
    expect(CORE_MANIFESTS['core.terminal']!.capabilities).toContain('terminal-input');
  });

  test('every manifest is plain data that survives a JSON round trip', () => {
    for (const manifest of Object.values(CORE_MANIFESTS)) {
      expect(JSON.parse(JSON.stringify(manifest))).toEqual(manifest);
    }
  });
});

describe('manifestForSlot', () => {
  test('maps singletons, row-keyed terminals, the primary and browsers', () => {
    expect(manifestForSlot('notes')?.id).toBe('core.notes');
    expect(manifestForSlot('terminal:row:7')?.id).toBe('core.terminal');
    expect(manifestForSlot('terminal:@primary')?.id).toBe('core.terminal');
    expect(manifestForSlot('browser:b1')?.id).toBe('core.browser');
  });

  test('answers undefined, never throws, for a slot no widget covers', () => {
    expect(manifestForSlot('spotify' as never)).toBeUndefined();
  });
});

describe('the manifest layer imports no component', () => {
  test('no widgets/ source file imports a .svelte file except by type', () => {
    const sources = import.meta.glob('./*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
    const offenders = Object.entries(sources)
      .filter(([path]) => !path.endsWith('.test.ts'))
      .filter(([, text]) => /^import (?!type )[^;]*\.svelte'/m.test(text))
      .map(([path]) => path);
    expect(Object.keys(sources).length).toBeGreaterThan(3);
    expect(offenders).toEqual([]);
  });
});
