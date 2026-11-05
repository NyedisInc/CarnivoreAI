/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { flushSync } from 'svelte';
import { setLocale } from '../i18n/index.svelte';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { refreshRailDockNames, startRailDockNames } from './rail-dock-names.svelte';
import { rail, railOn, setupRail, teardownRail } from './fixtures/rail-harness';

setLocale('en');

beforeEach(async () => {
  await setupRail();
});

afterEach(async () => {
  delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
  layoutEditor.active = false;
  flushSync();
  await teardownRail();
});

const frame = (): Promise<void> => new Promise((done) => requestAnimationFrame(() => done()));
const CELL_PITCH_PX = 30;

function cells(): HTMLElement[] {
  const all = [...rail().querySelectorAll<HTMLElement>('[data-dock-name]')];
  all.forEach((el, i) => {
    el.getBoundingClientRect = () => new DOMRect(0, i * CELL_PITCH_PX, 28, 28);
  });
  return all;
}

function moveOver(cell: HTMLElement): void {
  const host = rail().querySelector<HTMLElement>('nav.sbr-rail')!;
  const box = cell.getBoundingClientRect();
  host.dispatchEvent(Object.assign(new MouseEvent('pointermove', { bubbles: true, clientY: box.top + box.height / 2 }), { pointerType: 'mouse' }));
}

test('edit layout: a pointer move sets no --dock-s, and turning edit layout on clears one already set', async () => {
  await railOn();
  const all = cells();
  moveOver(all[1]!);
  await frame();
  expect(all[1]!.style.getPropertyValue('--dock-s'), 'outside edit layout it magnifies').not.toBe('');

  layoutEditor.active = true;
  flushSync();
  expect(all.some((c) => c.style.getPropertyValue('--dock-s') !== ''), 'turning edit layout on clears the magnification').toBe(false);

  moveOver(cells()[1]!);
  await frame();
  expect(cells().some((c) => c.style.getPropertyValue('--dock-s') !== ''), 'in edit layout the pointer magnifies nothing').toBe(false);
});

test('docking: a pointer move outside edit layout zooms the layers in (data-docking, then data-dock-live), and never while editing', async () => {
  await railOn();
  const nav = rail().querySelector<HTMLElement>('nav.sbr-rail')!;
  const first = cells();
  moveOver(first[1]!);
  await frame();
  expect(nav.hasAttribute('data-docking'), 'outside edit layout the layers zoom in').toBe(true);
  expect(nav.hasAttribute('data-dock-live'), 'and the transition is enabled only after that step').toBe(true);

  nav.dispatchEvent(new MouseEvent('pointerleave'));
  await new Promise((done) => setTimeout(done, 120));
  expect(nav.hasAttribute('data-docking') || nav.hasAttribute('data-dock-live'), 'after the ease both are gone').toBe(false);

  layoutEditor.active = true;
  flushSync();
  moveOver(cells()[1]!);
  await frame();
  expect(nav.hasAttribute('data-docking'), 'in edit layout the layers never zoom').toBe(false);
  expect(nav.hasAttribute('data-dock-live')).toBe(false);
});

test('a cell mounted while docked drops the dock at once, so it never grows to the zoomed box', async () => {
  await railOn();
  const nav = rail().querySelector<HTMLElement>('nav.sbr-rail')!;
  moveOver(cells()[1]!);
  await frame();
  expect(nav.hasAttribute('data-docking'), 'docked').toBe(true);

  const late = document.createElement('span');
  late.className = 'sbr-rail__cell';
  late.dataset.dockName = 'late';
  nav.querySelector('[data-rail-zone]')!.append(late);
  await new Promise((done) => setTimeout(done, 0));
  expect(nav.hasAttribute('data-docking') || nav.hasAttribute('data-dock-live'), 'a new cell ends the dock at once').toBe(false);
  expect(cells().some((c) => c.style.getPropertyValue('--dock-w') !== ''), 'and no frozen box is left behind').toBe(false);
});

function storeMagnify(first: unknown): (next: unknown) => void {
  let stored = first;
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
    read: (field: string, local: () => unknown) => (field === 'rail_magnify' && stored !== undefined ? stored : local()),
    write: async () => ({ status: 'committed' }),
    writeMany: async () => ({ status: 'committed' }),
    follow: () => () => {},
  };
  return (next) => {
    stored = next;
  };
}

function storeNames(first: unknown): (next: unknown) => void {
  let stored = first;
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
    read: (field: string, local: () => unknown) => (field === 'rail_dock_names' && stored !== undefined ? stored : local()),
    write: async () => ({ status: 'committed' }),
    writeMany: async () => ({ status: 'committed' }),
    follow: () => () => {},
  };
  return (next) => {
    stored = next;
  };
}

async function peakAfterHover(): Promise<string> {
  const all = cells();
  moveOver(all[1]!);
  await frame();
  const peak = all[1]!.style.getPropertyValue('--dock-s');
  rail().querySelector<HTMLElement>('nav.sbr-rail')!.dispatchEvent(new MouseEvent('pointerleave'));
  await new Promise((done) => setTimeout(done, 120));
  return peak;
}

test('the magnify setting sets the peak scale live: the stored size, the default when absent, and off magnifies nothing', async () => {
  await railOn();
  const set = storeMagnify(undefined);
  expect(await peakAfterHover(), 'absent reads as the built 1.5').toBe('1.5');

  set(200);
  expect(await peakAfterHover(), 'a stored 200 percent peaks at 2, read at once with no reload').toBe('2');
  set(125);
  expect(await peakAfterHover()).toBe('1.25');

  set(100);
  expect(await peakAfterHover(), 'off: no magnification').toBe('');
  expect(rail().querySelector<HTMLElement>('nav.sbr-rail')!.hasAttribute('data-docking'), 'and the layers never zoom').toBe(false);

  set(175);
  layoutEditor.active = true;
  flushSync();
  expect(await peakAfterHover(), 'edit layout never magnifies, whatever the setting').toBe('');
});

function nameShownFor(cell: HTMLElement): boolean {
  cell.dispatchEvent(new MouseEvent('pointerover', { bubbles: true }));
  flushSync();
  return rail().querySelector('.sbr-rail__label')!.classList.contains('sbr-rail__label--on');
}

test('the show-button-names setting gates the hovered key\'s name, live, and edit layout never shows one', async () => {
  await railOn();
  const set = storeNames(undefined);
  expect(nameShownFor(cells()[1]!), 'absent reads as on').toBe(true);

  set(false);
  startRailDockNames();
  refreshRailDockNames();
  flushSync();
  expect(nameShownFor(cells()[2]!), 'a stored false hides the name').toBe(false);

  set(true);
  refreshRailDockNames();
  flushSync();
  expect(nameShownFor(cells()[2]!), 'back on, it shows again').toBe(true);

  layoutEditor.active = true;
  flushSync();
  expect(nameShownFor(cells()[1]!), 'edit layout never shows a name').toBe(false);
});
