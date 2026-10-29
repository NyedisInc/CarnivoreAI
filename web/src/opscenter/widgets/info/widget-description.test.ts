import { describe, expect, test } from 'vitest';
import { CORE_MANIFESTS } from '../core-manifests';
import { widgetDescription, widgetMaker, widgetPlaces } from './widget-description';

describe('widgetDescription', () => {
  test('every widget goes on a dashboard, the terminal page and the sidebar; a glance needs a declared tile', () => {
    const ledger = CORE_MANIFESTS['core.ledger']!;
    expect(widgetPlaces(ledger, 36)).toEqual(['dashboard', 'terminal', 'sidebar', 'glance']);
    expect(widgetPlaces(ledger, null)).toEqual(['dashboard', 'terminal', 'sidebar']);
    const notes = CORE_MANIFESTS['core.notes']!;
    expect(widgetPlaces(notes, null)).toEqual(['dashboard', 'terminal', 'sidebar']);
  });

  test('a core widget is built in; any other namespace is a plugin, named by its vendor', () => {
    expect(widgetMaker('core.notes')).toEqual({ kind: 'built-in', vendor: 'core' });
    expect(widgetMaker('acme.weather')).toEqual({ kind: 'plugin', vendor: 'acme' });
  });

  test('options are the declared settings labels, in order; none for a widget with nothing to set', () => {
    const withSettings = Object.values(CORE_MANIFESTS).find((manifest) => manifest.settings)!;
    expect(widgetDescription(withSettings).options).toEqual(Object.values(withSettings.settings!.fields).map((field) => field.labelKey));
    const without = Object.values(CORE_MANIFESTS).find((manifest) => !manifest.settings)!;
    expect(widgetDescription(without).options).toEqual([]);
  });
});
