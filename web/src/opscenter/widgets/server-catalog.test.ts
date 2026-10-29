import { describe, expect, test } from 'vitest';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

import { CORE_MANIFESTS } from './core-manifests';
import { declarationOf, FitDeclarationError } from './fit-declarations';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';

interface ServerRow {
  id: string;
  instancing: string;
  settings?: unknown;
  fits?: unknown;
}

const file = fileURLToPath(new URL('../../../../src/data/widgets.json', import.meta.url));
const declared = (JSON.parse(fs.readFileSync(file, 'utf8')) as { widgets: ServerRow[] }).widgets;
const manifests = Object.values(CORE_MANIFESTS);

describe('src/data/widgets.json', () => {
  test('there are widgets on both sides (the control for every loop below)', () => {
    expect(manifests.length).toBeGreaterThanOrEqual(14);
    expect(declared.length).toBe(manifests.length);
  });

  test('names every manifest, in the same order, with the same instancing', () => {
    expect(declared.map((row) => [row.id, row.instancing])).toEqual(
      manifests.map((manifest) => [manifest.id, manifest.instancing]),
    );
  });

  test('carries each settings contribution exactly', () => {
    for (const manifest of manifests) {
      const row = declared.find((entry) => entry.id === manifest.id)!;
      expect(row.settings, manifest.id).toEqual(JSON.parse(JSON.stringify(manifest.settings ?? null)) ?? undefined);
    }
  });

  test('is the ONE declaration of each capability contract, read by the manifests and the server (issue #1157)', () => {
    for (const manifest of manifests) {
      const row = declared.find((entry) => entry.id === manifest.id)!;
      const { min: _derived, ...declaredHalf } = JSON.parse(JSON.stringify(manifest.fits));
      expect(row.fits ?? {}, manifest.id).toEqual(declaredHalf);
      expect(Object.keys((row.fits ?? {}) as object), manifest.id).not.toContain('min');
    }
    const first = manifests[0]!;
    const row = declared.find((entry) => entry.id === first.id)!;
    expect({ ...((row.fits ?? {}) as object), sizes: ['full'] }).not.toEqual(row.fits ?? {});
  });

  test('a widget with no row, no fits, an unknown size name or a retired key fails loudly at load', () => {
    expect(() => declarationOf('notes', [])).toThrow(FitDeclarationError);
    expect(() => declarationOf('notes', [{ id: 'core.notes' }])).toThrow(/declares no fits/);
    expect(() => declarationOf('notes', [{ id: 'core.notes', fits: { sizes: ['2x2'] } }])).toThrow(/not a size name/);
    expect(() => declarationOf('notes', [{ id: 'core.notes', fits: { sizes: ['wide', 'wide'] } }])).toThrow(/repeats/);
    expect(() => declarationOf('notes', [{ id: 'core.notes', fits: { sizes: ['wide'], anySize: 'yes' } }])).toThrow(/anySize/);
    for (const retired of ['zones', 'suggested', 'tested', 'max', 'allowed']) {
      expect(() => declarationOf('notes', [{ id: 'core.notes', fits: { sizes: ['medium'], [retired]: [] } }])).toThrow(new RegExp(`fits.${retired} is retired`));
    }
    expect(declarationOf('notes', [{ id: 'core.notes', fits: { sizes: ['medium', 'large'] } }])).toEqual({ sizes: ['medium', 'large'], anySize: false });
    expect(declarationOf('notes', [{ id: 'core.notes', fits: { sizes: ['medium'], anySize: true } }]).anySize).toBe(true);
  });

  test('at least one widget declares settings, and every label is in the string catalog', () => {
    const withSettings = manifests.filter((manifest) => manifest.settings);
    expect(withSettings.length).toBeGreaterThanOrEqual(1);
    const catalog = enCatalog as Record<string, string>;
    for (const manifest of withSettings) {
      for (const field of Object.values(manifest.settings!.fields)) {
        expect(catalog[field.labelKey], field.labelKey).toBeTypeOf('string');
      }
    }
  });
});
