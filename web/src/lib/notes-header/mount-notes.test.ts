/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const panels = vi.hoisted(() => ({ mounted: [] as string[], unmounted: [] as string[] }));

vi.mock('../mount', () => ({
  mountPanel: (id: string) => {
    panels.mounted.push(id);
    return {};
  },
  unmountPanel: (id: string) => {
    panels.unmounted.push(id);
    return true;
  },
}));

vi.mock('../../opscenter/cells/notes/Cell.svelte', () => ({ default: () => ({}) }));
vi.mock('./NotesDrawer.svelte', () => ({ default: () => ({}) }));

const saves = vi.hoisted(() => ({ count: 0 }));

vi.mock('../../opscenter/api/notes.svelte', () => ({
  saveAll: () => {
    saves.count += 1;
    return Promise.resolve();
  },
}));

import { terminalLayout } from '../../opscenter/engine/layout.svelte';
import {
  NOTES_BUTTON_ID,
  NOTES_PANEL_ID,
  mountSessionNotes,
  notesAreOpen,
  openNotesAsComponent,
  toggleSessionNotes,
  unmountSessionNotes,
} from './mount-notes';
import { closeDrawer, openDrawer, registerOccupant, resetRightDrawerForTest } from '../right-drawer/dock.svelte';

/** Say whether this browser reports itself wide enough for the grid. */
function setWidth(isWide: boolean): void {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => ({ matches: isWide, media: query }),
  });
}

function buildPage(): HTMLElement {
  document.body.innerHTML = '';
  const screen = document.createElement('div');
  screen.id = 'terminal-screen';
  document.body.appendChild(screen);
  const btn = document.createElement('button');
  btn.id = NOTES_BUTTON_ID;
  btn.className = 'btn-icon hidden';
  document.body.appendChild(btn);
  return btn;
}

function cellUp(): boolean {
  return !terminalLayout.state.layout.hidden.includes('notes');
}

beforeEach(() => {
  panels.mounted.length = 0;
  panels.unmounted.length = 0;
  saves.count = 0;
  setWidth(true);
  terminalLayout.resetAll();
  resetRightDrawerForTest();
});

afterEach(() => {
  unmountSessionNotes();
  document.body.innerHTML = '';
});

describe('above the grid width the control opens the right drawer', () => {
  test('the page opens with the notepad off the surface', () => {
    expect(cellUp()).toBe(false);
    expect(notesAreOpen()).toBe(false);
  });

  test('one click slides the drawer in, docked, and another takes it away', () => {
    const btn = buildPage();
    expect(mountSessionNotes()).toBe(true);

    btn.click();
    expect(panels.mounted).toEqual([NOTES_PANEL_ID]);
    expect(document.getElementById(NOTES_PANEL_ID)).not.toBeNull();
    expect(document.body.classList.contains('right-drawer-docked')).toBe(true);
    expect(cellUp()).toBe(false);
    expect(btn.getAttribute('aria-pressed')).toBe('true');

    btn.click();
    expect(document.getElementById(NOTES_PANEL_ID)).toBeNull();
    expect(document.body.classList.contains('right-drawer-docked')).toBe(false);
    expect(btn.getAttribute('aria-pressed')).toBe('false');
  });

  test('taking it off writes the note first', () => {
    const btn = buildPage();
    mountSessionNotes();
    btn.click();
    saves.count = 0;
    btn.click();
    expect(saves.count).toBe(1);
  });

  test('a notes cell already in the grid is what the same icon takes away', () => {
    const btn = buildPage();
    mountSessionNotes();
    terminalLayout.show('notes');
    expect(notesAreOpen()).toBe(true);
    btn.click();
    expect(cellUp()).toBe(false);
    expect(panels.mounted).toEqual([]);
    expect(btn.getAttribute('aria-pressed')).toBe('false');
  });

  test('open as component swaps the drawer for the grid cell', () => {
    const btn = buildPage();
    mountSessionNotes();
    btn.click();
    openNotesAsComponent();
    expect(document.getElementById(NOTES_PANEL_ID)).toBeNull();
    expect(cellUp()).toBe(true);
    expect(notesAreOpen()).toBe(true);
    expect(btn.getAttribute('aria-pressed')).toBe('true');
  });

  test('the file browser taking the slot closes the notepad, with its save', () => {
    const btn = buildPage();
    mountSessionNotes();
    btn.click();
    saves.count = 0;
    const files = document.createElement('div');
    document.body.appendChild(files);
    registerOccupant('files', { root: files, box: files, close: () => closeDrawer('files') });
    openDrawer('files');
    expect(document.getElementById(NOTES_PANEL_ID)).toBeNull();
    expect(saves.count).toBe(1);
    expect(btn.getAttribute('aria-pressed')).toBe('false');
    closeDrawer('files');
  });

  test('wiring twice installs one listener', () => {
    const btn = buildPage();
    mountSessionNotes();
    mountSessionNotes();
    btn.click();
    expect(notesAreOpen()).toBe(true);
  });
});

describe('below the grid width the control opens the same drawer, undocked', () => {
  test('a click mounts the notepad into a container of its own', () => {
    setWidth(false);
    const btn = buildPage();
    mountSessionNotes();

    btn.click();
    expect(panels.mounted).toEqual([NOTES_PANEL_ID]);
    expect(document.getElementById(NOTES_PANEL_ID)).not.toBeNull();
    expect(btn.getAttribute('aria-pressed')).toBe('true');
    expect(cellUp()).toBe(false);

    btn.click();
    expect(panels.unmounted).toContain(NOTES_PANEL_ID);
    expect(document.getElementById(NOTES_PANEL_ID)).toBeNull();
    expect(btn.getAttribute('aria-pressed')).toBe('false');
  });

  test('on a phone the drawer is an overlay, never docked', () => {
    setWidth(false);
    const prior = window.innerWidth;
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 });
    try {
      const btn = buildPage();
      mountSessionNotes();
      btn.click();
      expect(document.getElementById(NOTES_PANEL_ID)).not.toBeNull();
      expect(document.body.classList.contains('right-drawer-docked')).toBe(false);
    } finally {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: prior });
    }
  });

  test('the phone path never touches the layout', () => {
    setWidth(false);
    const btn = buildPage();
    mountSessionNotes();
    btn.click();
    expect(cellUp()).toBe(false);
  });

  test('closing the panel writes the note', () => {
    setWidth(false);
    const btn = buildPage();
    mountSessionNotes();
    btn.click();
    saves.count = 0;
    btn.click();
    expect(saves.count).toBe(1);
  });
});

describe('the control on a page that does not carry it', () => {
  test('mounting is a no-op rather than a fault', () => {
    document.body.innerHTML = '';
    expect(mountSessionNotes()).toBe(false);
  });
});
