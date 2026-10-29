/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/cells/notes/Cell.svelte', async () => ({ default: (await import('./fixtures/NotesCellStub.svelte')).default }));

import NotesDrawer from '../notes-header/NotesDrawer.svelte';
import { closeDrawer, openDrawer, registerOccupant, registerOpener, resetRightDrawerForTest, rightDrawer, selectDrawer } from './dock.svelte';
import { NOTES_HEADER_ID, rightDrawerZone } from './zone.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

let target: HTMLElement;
let app: ReturnType<typeof mount> | null;
let notesClosed: number;
let filesClosed: number;
let componentAsked: number;
let closeAsked: number;

function openNotes(): void {
  openDrawer('notes');
  app ??= mount(NotesDrawer, {
    target,
    props: { onClose: () => { closeAsked += 1; }, onComponent: () => { componentAsked += 1; }, canComponent: () => true },
  });
  flushSync();
}

const pane = (key: string): HTMLElement | null => target.querySelector(`[data-zone-pane="${key}"]`);
const heads = (): NodeListOf<HTMLElement> => target.querySelectorAll('[data-widget-head]');

beforeEach(() => {
  resetRightDrawerForTest();
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  target = document.createElement('div');
  document.body.appendChild(target);
  app = null;
  notesClosed = 0;
  filesClosed = 0;
  componentAsked = 0;
  closeAsked = 0;
  const notesRoot = document.createElement('div');
  const filesRoot = document.createElement('div');
  registerOccupant('notes', { root: notesRoot, box: notesRoot, close: () => { notesClosed += 1; closeDrawer('notes'); } });
  registerOccupant('files', { root: filesRoot, box: filesRoot, close: () => { filesClosed += 1; closeDrawer('files'); } });
  registerOpener('notes', openNotes);
  registerOpener('files', () => openDrawer('files'));
});

afterEach(() => {
  if (app) unmount(app);
  resetRightDrawerForTest();
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

describe('the right drawer zone', () => {
  test('nothing open: no active tab, the panel closed, both tabs parked', () => {
    expect(rightDrawerZone.tabs.map((one) => one.key)).toEqual(['files', 'notes']);
    expect(rightDrawerZone.active).toBeNull();
    expect(rightDrawerZone.visibility('notes')).toBe('parked');
    expect(rightDrawerZone.visibility('files')).toBe('parked');
  });

  test('opening notes then files shows files, closes notes through its own path, and notes reads hidden', () => {
    openNotes();
    expect(rightDrawerZone.active?.key).toBe('notes');
    expect(rightDrawerZone.visibility('notes')).toBe('shown');
    expect(pane('notes')?.dataset['zoneVisible']).toBe('shown');
    expect(heads()).toHaveLength(1);

    openDrawer('files');
    flushSync();
    expect(notesClosed).toBe(1);
    expect(rightDrawerZone.active?.key).toBe('files');
    expect(rightDrawerZone.visibility('files')).toBe('shown');
    expect(rightDrawerZone.visibility('notes')).toBe('hidden');
    expect(pane('notes'), 'the shell mounts the active tab only').toBeNull();
    expect(heads()).toHaveLength(0);
  });

  test('closing keeps the last opened tab active and parks both; select reopens a tab through its own door', () => {
    openNotes();
    openDrawer('files');
    closeDrawer('files');
    flushSync();
    expect(rightDrawer.kind).toBeNull();
    expect(rightDrawerZone.active?.key).toBe('files');
    expect(rightDrawerZone.visibility('files')).toBe('parked');

    rightDrawerZone.spec.select('notes');
    flushSync();
    expect(rightDrawerZone.active?.key).toBe('notes');
    expect(pane('notes')?.dataset['zoneVisible']).toBe('shown');
    expect(selectDrawer('notes'), 'selecting the tab on show is a no-op').toBe(true);
    expect(filesClosed).toBe(0);
  });

  test('one header row: the tab\'s own header, its declared actions and the drawer\'s in the one menu, close last', () => {
    openNotes();
    const row = heads()[0]!;
    expect(rightDrawerZone.headerFor('notes').hostId).toBe(NOTES_HEADER_ID);
    row.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
    flushSync();
    const items = [...document.querySelectorAll<HTMLElement>('[role="menu"] [role^="menuitem"]')].map((one) => one.textContent?.trim() ?? '');
    expect(items.some((one) => one.includes('preview')), 'the cell\'s declared action').toBe(true);
    expect(items.some((one) => one.includes('open as widget')), 'the drawer\'s own door').toBe(true);
    expect(items[items.length - 1]).toContain('close');
    const asWidget = [...document.querySelectorAll<HTMLElement>('[role="menu"] [role^="menuitem"]')].find((one) => one.textContent?.includes('open as widget'))!;
    asWidget.click();
    flushSync();
    expect(componentAsked).toBe(1);

    row.querySelector<HTMLElement>('[data-head-close]')!.click();
    expect(closeAsked).toBe(1);
  });
});
