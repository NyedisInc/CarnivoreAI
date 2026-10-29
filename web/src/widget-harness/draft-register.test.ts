import { describe, expect, it } from 'vitest';
import { registerDraftWidget, type DraftSpec } from './draft-register';
import { harnessWidget } from './catalog';
import { CORE_MANIFESTS, manifestById, manifestForSlot } from '../opscenter/widgets/core-manifests';
import { draftLabWidget } from '../cplugs/sdk/widget-lab';
import { itemPath } from '../lib/item-settings/api';

const SPEC: DraftSpec = {
  id: 'core.hosts-probe',
  slot: 'hosts-probe',
  title: 'Hosts probe',
  instancing: 'singleton',
  hosts: ['home', 'terminal', 'drawer', 'popout'],
  category: 'monitoring',
  type: 'list',
  capabilities: [],
  fits: { sizes: ['small', 'wide'], anySize: true, max_per_surface: 1 },
  cell: {
    icon: 'grid', iconTone: 'cyan', minPx: 220, minHeight: 88,
    widthStates: [{ name: 'name', min: 220 }], heightStates: [{ name: 'title', min: 0 }, { name: 'rows', min: 88 }],
  } as DraftSpec['cell'],
};

describe('a draft widget registered at run time', () => {
  registerDraftWidget({ spec: SPEC, component: (() => undefined) as never, fixtures: { data: {}, empty: {} } as never });

  it('has a manifest the drawer area and the slide-outs can read, though the core table is frozen', () => {
    expect(Object.isFrozen(CORE_MANIFESTS)).toBe(true);
    expect(CORE_MANIFESTS['core.hosts-probe']).toBeUndefined();
    const manifest = manifestById('core.hosts-probe');
    expect(manifest?.id).toBe('core.hosts-probe');
    expect(manifest?.category).toBe('monitoring');
    expect(manifest?.canvases).toEqual(['home', 'terminal']);
    expect(manifestForSlot('hosts-probe' as never)?.id).toBe('core.hosts-probe');
    expect(manifestById('core.notes')).toBe(CORE_MANIFESTS['core.notes']);
  });

  it('is drawn with sizes in the drawer and the pop-out as well as the grids', () => {
    const widget = harnessWidget('core.hosts-probe')!;
    expect(widget.zones).toEqual(['home', 'terminal', 'drawer', 'popout']);
    for (const zone of widget.zones) expect(widget.sizes[zone]?.length, zone).toBeGreaterThan(0);
  });

  it('is declared in every host by the lab, and a host it does not name stays undeclared', () => {
    const all = draftLabWidget({ id: SPEC.id, title: SPEC.title, hosts: [...SPEC.hosts], fits: SPEC.fits, cell: { minPx: 220, minHeight: 88 }, category: 'monitoring' });
    expect(all.hosts.map((host) => [host.zone, host.supported])).toEqual([['home', true], ['terminal', true], ['drawer', true], ['popout', true]]);
    const grids = draftLabWidget({ id: SPEC.id, title: SPEC.title, hosts: ['home', 'terminal'], fits: SPEC.fits, cell: { minPx: 220, minHeight: 88 } });
    expect(grids.hosts.map((host) => [host.zone, host.supported])).toEqual([['home', true], ['terminal', true], ['drawer', false], ['popout', false]]);
  });
});

describe('a draft with the options a built-in declares', () => {
  const SETTINGS = {
    version: 1,
    fields: { showGlobalFolder: { kind: 'boolean', labelKey: 'widgets.setting.files.show_global_folder', default: true } },
  } as unknown as NonNullable<DraftSpec['settings']>;
  registerDraftWidget({
    spec: { ...SPEC, id: 'core.files-copy', slot: 'files-copy', settings: SETTINGS, scope: 'session', keepAlive: null, looks: null, views: null },
    component: (() => undefined) as never,
    fixtures: { data: {}, empty: {} } as never,
  });

  it('carries settings and scope into its manifest, and leaves null options out', () => {
    const manifest = manifestById('core.files-copy');
    expect(manifest?.settings).toEqual(SETTINGS);
    expect(manifest?.scope).toBe('session');
    expect(manifest && 'keepAlive' in manifest).toBe(false);
    expect(manifest && 'views' in manifest).toBe(false);
  });

  it('reads and writes every widget setting under its own id, never the shipped widget it copies', () => {
    expect(itemPath('widget', 'core.files')).toBe('/item-settings/widget/core.files-copy');
    expect(itemPath('plugin', 'huddle')).toBe('/item-settings/plugin/huddle');
  });
});
