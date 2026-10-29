import { describe, expect, test } from 'vitest';
import { validateManifest } from './validate';
import type { ManifestRefusal } from './types';

function good(): Record<string, unknown> {
  return {
    id: 'acme.now-playing',
    version: '1.2.0',
    titleKey: 'widgets.acme.now_playing.title',
    icon: 'music',
    iconTone: 'oc-cyan',
    category: 'tools',
    type: 'tool',
    instancing: 'singleton',
    canvases: ['home'],
    bounds: { minW: 200, minH: 60, maxW: 900 },
    fits: { min: { w: 2, h: 1 }, sizes: ['wide', 'large'], anySize: false },
    densities: {
      width: [
        { name: 'narrow', min: 0 },
        { name: 'wide', min: 400 },
      ],
      height: [{ name: 'line', min: 0 }],
    },
    settings: {
      version: 1,
      fields: {
        showArt: { kind: 'boolean', labelKey: 'widgets.acme.show_art', default: true },
        rows: { kind: 'number', labelKey: 'widgets.acme.rows', default: 3, min: 1, max: 10 },
        source: { kind: 'enum', labelKey: 'widgets.acme.source', options: ['a', 'b'], default: 'a' },
        caption: { kind: 'string', labelKey: 'widgets.acme.caption', default: '', maxLength: 40 },
      },
    },
    capabilities: [],
  };
}

function refusalOf(mutate: (m: Record<string, any>) => void): { refusal: ManifestRefusal | null; detail: string } {
  const manifest = good();
  mutate(manifest);
  const check = validateManifest(manifest);
  return check.ok ? { refusal: null, detail: '' } : { refusal: check.refusal, detail: check.detail };
}

describe('validateManifest', () => {
  test('a complete manifest passes and comes back unchanged', () => {
    const manifest = good();
    const check = validateManifest(manifest);
    expect(check.ok).toBe(true);
    if (check.ok) expect(check.manifest).toBe(manifest);
  });

  test('a snake_case settings key passes (kind_all already ships)', () => {
    expect(refusalOf((m) => { m.settings.fields.kind_all = { kind: 'boolean', labelKey: 'widgets.acme.kind_all', default: true }; }).refusal).toBeNull();
  });

  test('a settings key starting with an underscore is refused', () => {
    expect(refusalOf((m) => { m.settings.fields._bad = { kind: 'boolean', labelKey: 'widgets.acme.bad', default: true }; }).refusal).toBe('settings');
  });

  test('a manifest with no settings and no maximum passes', () => {
    expect(refusalOf((m) => { delete m.settings; delete m.bounds.maxW; }).refusal).toBeNull();
  });

  test.each<[string, unknown]>([
    ['null', null],
    ['an array', []],
    ['a string', 'core.notes'],
  ])('%s is refused as not-an-object', (_label, value) => {
    const check = validateManifest(value);
    expect(check.ok).toBe(false);
    if (!check.ok) expect(check.refusal).toBe('not-an-object');
  });

  test.each<[ManifestRefusal, string, (m: Record<string, any>) => void]>([
    ['unknown-field', 'a misspelt field', (m) => { m.catgeory = 'tools'; }],
    ['bounds', 'a misspelt nested bounds field (u166-02)', (m) => { m.bounds.minWidth = 4; }],
    ['fits', 'a misspelt nested fits field', (m) => { m.fits.anysize = true; }],
    ['densities', 'a misspelt density step field', (m) => { m.densities.width[0].minn = 1; }],
    ['settings', 'a misspelt settings field key', (m) => { m.settings.fields.rows.mx = 3; }],
    ['settings', 'a number whose min is above its max', (m) => { Object.assign(m.settings.fields.rows, { min: 9, max: 2, default: 3 }); }],
    ['settings', 'a disabledWhen naming no field', (m) => { m.settings.fields.showArt.disabledWhen = 'ghost'; }],
    ['settings', 'a disabledWhen naming a non-boolean field', (m) => { m.settings.fields.showArt.disabledWhen = 'rows'; }],
    ['settings', 'a disabledWhen naming itself', (m) => { m.settings.fields.showArt.disabledWhen = 'showArt'; }],
    ['fits', 'no fits declaration', (m) => { delete m.fits; }],
    ['fits', 'a retired zone list (every widget goes everywhere)', (m) => { m.fits.zones = ['home']; }],
    ['fits', 'a retired suggested list', (m) => { m.fits.suggested = [{ w: 2, h: 1 }]; }],
    ['fits', 'a retired tested list (sizes are named now)', (m) => { m.fits.tested = [{ w: 2, h: 1 }]; }],
    ['fits', 'a retired ceiling', (m) => { m.fits.max = { w: 9, h: 4 }; }],
    ['fits', 'a retired closed size list', (m) => { m.fits.allowed = [{ w: 2, h: 1 }]; }],
    ['fits', 'a named size below the floor', (m) => { m.fits.sizes = ['small']; }],
    ['fits', 'a repeated named size', (m) => { m.fits.sizes = ['large', 'large']; }],
    ['fits', 'a size given in numbers, not by name', (m) => { m.fits.sizes = ['4x2']; }],
    ['fits', 'no named sizes', (m) => { m.fits.sizes = []; }],
    ['fits', 'anySize that is not true or false', (m) => { m.fits.anySize = 'yes'; }],
    ['fits', 'a size in half units', (m) => { m.fits.min = { w: 1.5, h: 1 }; }],
    ['id', 'an id with no namespace', (m) => { m.id = 'notes'; }],
    ['id', 'an id with capitals', (m) => { m.id = 'Acme.Player'; }],
    ['version', 'a two part version', (m) => { m.version = '1.2'; }],
    ['title-key', 'a title that is words, not a key', (m) => { m.titleKey = 'Now Playing'; }],
    ['icon', 'an empty icon', (m) => { m.icon = ''; }],
    ['icon-tone', 'a hex colour instead of a token', (m) => { m.iconTone = '#ff0000'; }],
    ['category', 'an unknown category', (m) => { m.category = 'music'; }],
    ['type', 'no type label', (m) => { delete m.type; }],
    ['type', 'an unknown type label', (m) => { m.type = 'gadget'; }],
    ['instancing', 'an unknown instancing', (m) => { m.instancing = 'many'; }],
    ['canvases', 'no canvas', (m) => { m.canvases = []; }],
    ['canvases', 'an unknown canvas', (m) => { m.canvases = ['home', 'sidebar']; }],
    ['canvases', 'a repeated canvas', (m) => { m.canvases = ['home', 'home']; }],
    ['bounds', 'a negative minimum', (m) => { m.bounds.minW = -1; }],
    ['bounds', 'a maximum below the minimum', (m) => { m.bounds.maxW = 100; }],
    ['densities', 'an empty width ladder', (m) => { m.densities.width = []; }],
    ['densities', 'a missing height ladder', (m) => { delete m.densities.height; }],
    ['densities', 'a ladder that does not rise', (m) => { m.densities.width[1].min = 0; }],
    ['densities', 'a repeated step name', (m) => { m.densities.width[1].name = 'narrow'; }],
    ['densities', 'a step name with a space', (m) => { m.densities.width[1].name = 'very wide'; }],
    ['densities', 'a step above the maximum', (m) => { m.densities.width[1].min = 1000; }],
    ['settings', 'a version of zero', (m) => { m.settings.version = 0; }],
    ['settings', 'a boolean with a word default', (m) => { m.settings.fields.showArt.default = 'yes'; }],
    ['settings', 'a number default above its max', (m) => { m.settings.fields.rows.default = 11; }],
    ['settings', 'an enum default not in its options', (m) => { m.settings.fields.source.default = 'c'; }],
    ['settings', 'a string default longer than maxLength', (m) => { m.settings.fields.caption.default = 'x'.repeat(41); }],
    ['settings', 'an unknown field kind', (m) => { m.settings.fields.rows.kind = 'color'; }],
    ['settings', 'a dotted field key reaching another namespace', (m) => { m.settings.fields['core.theme'] = m.settings.fields.showArt; }],
    ['settings', 'a label that is not a catalog key', (m) => { m.settings.fields.rows.labelKey = 'Rows'; }],
    ['capabilities', 'an unknown capability', (m) => { m.capabilities = ['network']; }],
    ['capabilities', 'a repeated capability', (m) => { m.capabilities = ['navigate', 'navigate']; }],
    ['keep-alive', 'an unknown keep-alive', (m) => { m.keepAlive = 'always'; }],
  ])('refuses as %s: %s', (refusal, _label, mutate) => {
    const answer = refusalOf(mutate);
    expect(answer.refusal).toBe(refusal);
    expect(answer.detail.length).toBeGreaterThan(0);
  });
});
