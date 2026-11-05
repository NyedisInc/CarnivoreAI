import { afterEach, describe, expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { harnessWidget } from './catalog';
import { hasFixture } from '../opscenter/widgets/fixtures';
import { panelOf, setPanels } from '../lib/cplug-ui/panel-views.svelte';
import { FIXTURE_KIND, FIXTURE_SLOT, registerPluginViewFixture } from './plugin-view-fixture';

afterEach(() => setPanels([]));

describe('the plugin view fixture', () => {
  test('registered, core.plugin-view is a catalog entry on its fixture slot with a fixture pair and the contract record sizes', () => {
    registerPluginViewFixture(true);
    const entry = harnessWidget('core.plugin-view');
    expect(entry?.slot).toBe(FIXTURE_SLOT);
    expect(entry?.zones).toEqual(['home', 'terminal', 'drawer']);
    expect(hasFixture('core.plugin-view')).toBe(true);
    const record = JSON.parse(readFileSync(resolve(__dirname, '../../../src/data/widget-contracts.json'), 'utf8')).widgets.find((w: { id: string }) => w.id === 'core.plugin-view');
    expect(panelOf(FIXTURE_KIND)?.fits.sizes).toEqual(record.sizes);
    expect(record.fixtures).toEqual(['data', 'empty']);
  });

  test('the empty fixture is the plugin turned off, its kind still registered', () => {
    registerPluginViewFixture(false);
    expect(panelOf(FIXTURE_KIND)).toBeUndefined();
    expect(harnessWidget('core.plugin-view')?.slot).toBe(FIXTURE_SLOT);
  });
});
