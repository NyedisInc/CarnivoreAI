/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import WidgetInfoCard from './WidgetInfoCard.svelte';
import { widgetInfo } from './widget-info';
import { CORE_MANIFESTS } from '../core-manifests';
import enCatalog from '../../../../../client/js/i18n/catalog.en.js';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('widget info', () => {
  test('the model reads the declaration: the named sizes, then "only at these sizes"; version', () => {
    const base = CORE_MANIFESTS['core.machine-stats']!;
    const manifest = { ...base, fits: { ...base.fits, sizes: ['full', 'medium'] as const, anySize: false } };
    const info = widgetInfo(manifest);
    expect(info.version).toBe(manifest.version);
    expect(info.sizes.slice(0, -1).map((line) => line.key)).toEqual(['widgets.size.medium', 'widgets.size.full']);
    expect(info.sizeNames).toEqual(['medium', 'full']);
    expect(info.sizes.at(-1)).toEqual({ key: 'widgets.info.size_tested_only' });
    expect(info).not.toHaveProperty('zones');
    expect(widgetInfo(base).sizes.at(-1)).toEqual({ key: 'widgets.info.size_any' });
  });

  test('a widget with a glance tile lists glance first; no size line carries a number', () => {
    const info = widgetInfo(CORE_MANIFESTS['core.ledger']!);
    expect(info.sizeNames[0]).toBe('glance');
    for (const manifest of Object.values(CORE_MANIFESTS)) {
      for (const line of widgetInfo(manifest).sizes) expect(line.params, manifest.id).toBeUndefined();
    }
  });

  test('the card lists the sizes by name only', () => {
    app = mount(WidgetInfoCard, { target: document.body, props: { info: widgetInfo(CORE_MANIFESTS['core.notes']!) } });
    flushSync();
    const sizes = document.querySelector('[data-widget-info-fact="sizes"]')?.textContent ?? '';
    expect(sizes).toContain('medium');
    expect(sizes).not.toMatch(/\d/);
  });

  test('every core widget has its about and data lines in the catalog', () => {
    const catalog = enCatalog as Record<string, unknown>;
    for (const manifest of Object.values(CORE_MANIFESTS)) {
      const info = widgetInfo(manifest);
      expect(catalog[info.about.key], info.about.key).toBeTypeOf('string');
      expect(catalog[info.data.key], info.data.key).toBeTypeOf('string');
      expect(catalog[info.instancingKey], info.instancingKey).toBeTypeOf('string');
      expect(catalog[info.categoryKey], info.categoryKey).toBeTypeOf('string');
    }
  });

  test('the card renders the facts in words', () => {
    app = mount(WidgetInfoCard, { target: document.body, props: { info: widgetInfo(CORE_MANIFESTS['core.activity-log']!) } });
    flushSync();
    const card = document.querySelector<HTMLElement>('[data-widget-info="core.activity-log"]')!;
    expect(card.querySelector('.oc-winfo-name')?.textContent).toBe('activity log');
    expect(card.querySelector('[data-widget-info-about]')?.textContent).toContain('running feed');
    expect(card.querySelector('[data-widget-info-fact="zones"]')).toBeNull();
    expect(card.querySelector('[data-widget-info-fact="data"]')?.textContent).toBe('the live event stream');
    expect(card.textContent).not.toMatch(/widgets\.info\./);
  });
});
