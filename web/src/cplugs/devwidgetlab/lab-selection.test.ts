/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { labWidgets } from '../sdk/widget-lab';
import { scaleFor, frameScale } from './fit-scale';
import { listenForMenuRequests, stopListeningForMenuRequests } from './menu-request';
import { applyIntent, appliedRoutes, bandSize, defaultSelection, flipIn, flipPlacement, placementsOn, framesOnShow, type DrawerDock, LAB_CHANNEL, normalizeFolds, normalizeSelection, selectWidget, sizeOptions } from './lab-selection';
import { installLabBus } from './lab-test-bus';
import { LabLink } from './lab-channel.svelte';

const widgets = labWidgets();
const notes = widgets.find((w) => w.key === 'core.notes')!;
const homeOnly = widgets.find((w) => w.hosts.some((h) => !h.supported))!;

describe('the selection', () => {
  it('starts on notes in every declared host at size m', () => {
    const sel = defaultSelection(widgets, 'carnivore');
    expect(sel).toMatchObject({ widget: 'core.notes', hosts: ['home', 'terminal', 'drawer', 'popout'], sizes: ['m'], theme: 'carnivore', fixture: 'data', focus: null });
  });

  it('reads garbage, a missing widget and wrong types as the default, field by field', () => {
    const base = defaultSelection(widgets, 'carnivore');
    expect(normalizeSelection(null, widgets, 'carnivore')).toEqual(base);
    expect(normalizeSelection('x', widgets, 'carnivore')).toEqual(base);
    expect(normalizeSelection({ widget: 'core.nope' }, widgets, 'carnivore')).toEqual(base);
    const odd = normalizeSelection({ widget: 'core.notes', hosts: ['mars'], sizes: [], theme: 4, fixture: 'weird', menu: 'yes', view: 'x', focus: { host: 1 } }, widgets, 'carnivore');
    expect(odd).toEqual(base);
    expect(normalizeFolds({ preview: 'no', matrix: true })).toEqual({ checks: true, preview: true, scenario: false, capture: true });
    expect(normalizeFolds({ checks: false })).toEqual({ checks: false, preview: true, scenario: false, capture: true });
    expect(normalizeFolds({ checks: null, preview: false, scenario: true })).toEqual({ checks: true, preview: false, scenario: true, capture: true });
  });

  it('keeps the picked sizes a new widget publishes, drops the rest, and never leaves hosts or sizes empty', () => {
    const sel = { ...defaultSelection(widgets, 'carnivore'), sizes: ['m', 'l'] };
    const next = selectWidget(sel, homeOnly);
    expect(next.hosts).toEqual(homeOnly.hosts.filter((h) => h.supported).map((h) => h.zone));
    expect(next.sizes.length).toBeGreaterThan(0);
    expect(flipIn(['m'], 'm')).toEqual(['m']);
    expect(flipIn(['m'], 'l')).toEqual(['m', 'l']);
  });

  it('puts on show each picked host the widget declares at that band\'s own size, and narrows to a focused frame', () => {
    const sel = { ...defaultSelection(widgets, 'carnivore'), hosts: ['home', 'terminal'], bandSizes: { terminal: 'l' } };
    expect(framesOnShow(notes, sel)).toEqual([{ host: 'home', size: 'm' }, { host: 'terminal', size: 'l' }]);
    expect(framesOnShow(notes, { ...sel, focus: { host: 'terminal', size: 'l' } })).toEqual([{ host: 'terminal', size: 'l' }]);
    expect(framesOnShow(notes, { ...sel, focus: { host: 'drawer', size: 'm' } }).length).toBe(2);
    expect(framesOnShow(undefined, sel)).toEqual([]);
  });

  it('resolves a band\'s size: its own choice where the host publishes it, else the first picked size for the page', () => {
    const home = notes.hosts.find((host) => host.zone === 'home')!;
    const sel = defaultSelection(widgets, 'carnivore');
    expect(bandSize(home, sel)?.name).toBe('m');
    expect(bandSize(home, { ...sel, bandSizes: { home: 'l' } })?.name).toBe('l');
    expect(bandSize(home, { ...sel, bandSizes: { home: 'nope' } })?.name).toBe('m');
    expect(bandSize(home, { ...sel, sizes: ['s'], bandSizes: {} })?.name).toBe('s');
  });

  it('switches one band\'s size with a size intent, only for a size that host publishes, and keeps the others', () => {
    const sel = { ...defaultSelection(widgets, 'carnivore'), hosts: ['home', 'terminal'] };
    const next = applyIntent(sel, { intent: 'size', host: 'home', size: 'l' }, widgets);
    expect(next.bandSizes).toEqual({ home: 'l' });
    expect(applyIntent(next, { intent: 'size', host: 'terminal', size: 's' }, widgets).bandSizes).toEqual({ home: 'l', terminal: 's' });
    expect(applyIntent(sel, { intent: 'size', host: 'home', size: 'nope' }, widgets)).toBe(sel);
    expect(applyIntent({ ...next, focus: { host: 'home', size: 'l' } }, { intent: 'size', host: 'home', size: 'm' }, widgets).focus).toBeNull();
  });

  it('reads a stored per-band size map safely: strings for declared hosts only', () => {
    const odd = normalizeSelection({ widget: 'core.notes', bandSizes: { home: 'l', mars: 'm', terminal: 3 } }, widgets, 'carnivore');
    expect(odd.bandSizes).toEqual({ home: 'l' });
    expect(normalizeSelection({ widget: 'core.notes', bandSizes: 'x' }, widgets, 'carnivore').bandSizes).toEqual({});
  });

  it('turns a fit-cell pick into widget, host and size, with that frame focused and on show', () => {
    const sel = { ...defaultSelection(widgets, 'carnivore'), widget: homeOnly.key, view: 'fit' as const };
    const next = applyIntent(sel, { intent: 'pick', widget: 'core.notes', host: 'terminal', size: 'l' }, widgets);
    expect(next).toMatchObject({ widget: 'core.notes', view: 'widget', focus: { host: 'terminal', size: 'l' } });
    expect(next.bandSizes).toEqual({ terminal: 'l' });
    expect(next.hosts).toContain('terminal');
    expect(applyIntent(sel, { intent: 'pick', widget: 'core.nope' }, widgets)).toBe(sel);
    expect(applyIntent(sel, { intent: 'open-menu' }, widgets)).toBe(sel);
  });

  it('counts an applied scenario\'s routes and reads text that does not parse as none', () => {
    expect(appliedRoutes(null)).toBe(0);
    expect(appliedRoutes('nope')).toBe(0);
    expect(appliedRoutes('{"GET /x": 1, "GET /y": 2}')).toBe(2);
  });
});

describe('the drawers', () => {
  const widgets = labWidgets();
  const docks = (raw: Record<string, unknown>) => normalizeSelection({ widget: 'core.notes', ...raw }, widgets, 'carnivore').docks;

  it('opens on all three drawers, in their own order, and keeps a stored list\'s valid names', () => {
    expect(defaultSelection(widgets, 'carnivore').docks).toEqual(['left', 'bottom', 'right']);
    expect(docks({ docks: ['bottom', 'left'] })).toEqual(['left', 'bottom']);
    expect(docks({ docks: ['sideways', 'right'] })).toEqual(['right']);
    expect(docks({ docks: ['sideways'] })).toEqual(['left', 'bottom', 'right']);
    expect(docks({ docks: 7 })).toEqual(['left', 'bottom', 'right']);
  });

  it('migrates the old single dock: left was the default and so opens all three, another keeps that drawer, junk opens all three', () => {
    expect(docks({ dock: 'left' })).toEqual(['left', 'bottom', 'right']);
    expect(docks({ dock: 'bottom' })).toEqual(['bottom']);
    expect(docks({ dock: 'right' })).toEqual(['right']);
    expect(docks({ dock: 'sideways' })).toEqual(['left', 'bottom', 'right']);
    expect(docks({ dock: 7 })).toEqual(['left', 'bottom', 'right']);
  });

  it('flips one drawer at a time, keeps the last one on, and counts one frame per chosen drawer', () => {
    const all = { hosts: ['home', 'drawer'], docks: ['left', 'bottom', 'right'] as DrawerDock[] };
    expect(flipPlacement(all, 'right')).toEqual({ hosts: ['home', 'drawer'], docks: ['left', 'bottom'] });
    expect(flipPlacement({ hosts: ['home', 'drawer'], docks: ['left', 'bottom'] }, 'right').docks).toEqual(['left', 'bottom', 'right']);
    expect(flipPlacement({ hosts: ['home', 'drawer'], docks: ['left'] }, 'left')).toEqual({ hosts: ['home'], docks: [] });
    expect(flipPlacement({ hosts: ['drawer'], docks: ['left'] }, 'left')).toEqual({ hosts: ['drawer'], docks: ['left'] });
    expect(flipPlacement({ hosts: ['home'], docks: [] }, 'bottom')).toEqual({ hosts: ['home', 'drawer'], docks: ['bottom'] });
    expect(placementsOn({ hosts: ['popout', 'drawer', 'home'], docks: ['right', 'left'] })).toEqual(['home', 'left', 'right', 'popout']);
    const notes = widgets.find((one) => one.key === 'core.notes')!;
    const sel = { ...defaultSelection(widgets, 'carnivore'), hosts: ['drawer'], docks: ['left', 'bottom'] as DrawerDock[] };
    expect(framesOnShow(notes, sel).map((frame) => frame.dock)).toEqual(['left', 'bottom']);
    expect(framesOnShow(notes, { ...sel, focus: { host: 'drawer', size: framesOnShow(notes, sel)[0]!.size, dock: 'bottom' } })).toHaveLength(1);
  });
});

describe('the phone scale', () => {
  it('shrinks a frame to the room it has, never grows it, never to nothing', () => {
    expect(scaleFor(300, 432)).toBeCloseTo(0.694, 2);
    expect(scaleFor(800, 432)).toBe(1);
    expect(scaleFor(0, 432)).toBe(1);
    expect(scaleFor(10, 432)).toBe(0.2);
    expect(frameScale(false, 300, 432)).toBe(1);
    expect(frameScale(true, 326, 432)).toBeCloseTo(0.694, 2);
  });
});

describe('the viewer\'s menu key', () => {
  beforeEach(() => {
    stopListeningForMenuRequests();
    installLabBus();
  });

  it('opens the slide-out in the main window when the viewer asks, once however many times it is set up', async () => {
    const open = vi.fn();
    listenForMenuRequests(open);
    listenForMenuRequests(open);
    const viewer = new BroadcastChannel(LAB_CHANNEL);
    viewer.postMessage({ kind: 'state' });
    viewer.postMessage({ kind: 'intent', intent: { intent: 'focus', focus: null } });
    await Promise.resolve();
    expect(open).not.toHaveBeenCalled();
    viewer.postMessage({ kind: 'intent', intent: { intent: 'open-menu' } });
    await Promise.resolve();
    await Promise.resolve();
    expect(open).toHaveBeenCalledTimes(1);
  });
});

describe('a draft changed in the menu', () => {
  beforeEach(() => installLabBus());

  it('tells the viewer, so its own store re-reads the folder (a build started in the menu used to leave the viewer on "not built yet")', async () => {
    const menu = new LabLink('menu', widgets, 'carnivore');
    const viewer = new LabLink('viewer', widgets, 'carnivore');
    expect(viewer.draftsSeq).toBe(0);
    menu.announceDrafts();
    await Promise.resolve();
    await Promise.resolve();
    expect(viewer.draftsSeq).toBe(1);
    viewer.announceDrafts();
    await Promise.resolve();
    expect(menu.draftsSeq).toBe(0);
    menu.destroy();
    viewer.destroy();
  });
});

describe('sizeOptions', () => {
  it('lists each published size once with its pixel widths, s m l as main and the rest as more', () => {
    const notes = widgets.find((one) => one.key === 'core.notes')!;
    const options = sizeOptions(notes);
    expect(new Set(options.map((one) => one.name)).size).toBe(options.length);
    for (const one of options) {
      expect(one.widths.length).toBeGreaterThan(0);
      expect(one.widths).toEqual([...one.widths].sort((a, b) => a - b));
      expect(one.main).toBe(['s', 'm', 'l'].includes(one.name));
    }
    expect(options.filter((one) => one.main).map((one) => one.name)).toEqual(expect.arrayContaining(['s', 'm', 'l']));
    expect(sizeOptions(undefined)).toEqual([]);
  });
});
