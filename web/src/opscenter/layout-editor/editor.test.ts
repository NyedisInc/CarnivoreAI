/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { homeLayout } from '../engine/layout.svelte';
import { onHomeChange } from '../engine/arrangement-events';
import type { LayoutPage } from '../engine/types';
import {
  EDITING_CLASS,
  addPanelWidget,
  addWidget,
  checkLayoutEditor,
  dropWidget,
  editorSeams,
  enterLayoutEditor,
  finishLayoutEditor,
  layoutEditor,
  removeWidget,
  toggleLayoutEditor,
} from './editor.svelte';

let page: LayoutPage | null = 'home';
let wide = true;
const real = { ...editorSeams };

const placed = (): string[] => homeLayout.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));

beforeEach(() => {
  page = 'home';
  wide = true;
  editorSeams.page = () => page;
  editorSeams.store = (p) => (p === 'home' ? homeLayout : null);
  editorSeams.wide = () => wide;
  homeLayout.resetAll();
});

afterEach(() => {
  finishLayoutEditor();
  Object.assign(editorSeams, real);
});

describe('entering and leaving', () => {
  test('toggle turns it on and marks the body, and off again', () => {
    expect(toggleLayoutEditor()).toBe(true);
    expect(layoutEditor.active).toBe(true);
    expect(layoutEditor.page).toBe('home');
    expect(document.body.classList.contains(EDITING_CLASS)).toBe(true);
    expect(document.body.dataset['layoutEditing']).toBe('home');
    expect(toggleLayoutEditor()).toBe(false);
    expect(layoutEditor.active).toBe(false);
    expect(document.body.classList.contains(EDITING_CLASS)).toBe(false);
  });

  test('refused below 1024 and on a screen with no surface', () => {
    wide = false;
    expect(enterLayoutEditor()).toBe(false);
    wide = true;
    page = null;
    expect(enterLayoutEditor()).toBe(false);
    expect(layoutEditor.active).toBe(false);
  });

  test('narrowing the window or leaving the screen ends the edit and keeps it', async () => {
    enterLayoutEditor();
    await addWidget('notes');
    wide = false;
    checkLayoutEditor();
    expect(layoutEditor.active).toBe(false);
    expect(placed()).toContain('notes');
    wide = true;
    enterLayoutEditor();
    page = 'terminal';
    checkLayoutEditor();
    expect(layoutEditor.active).toBe(false);
  });
});

describe('editing', () => {
  test('click add puts a hidden widget on the surface; remove hides it again', async () => {
    enterLayoutEditor();
    expect(placed()).not.toContain('notes');
    expect(await addWidget('notes')).toBe(true);
    expect(placed()).toContain('notes');
    expect(await removeWidget('notes')).toBe(true);
    expect(placed()).not.toContain('notes');
    expect(homeLayout.state.layout.hidden).toContain('notes');
  });

  test('a widget already on the surface is not added twice', async () => {
    enterLayoutEditor();
    expect(await addWidget('stat-running')).toBe(false);
  });

  test('drag-in lands at the target', async () => {
    enterLayoutEditor();
    expect(await dropWidget('files', { kind: 'new', after: null })).toBe('landed');
    expect(homeLayout.state.layout.rows[0]?.slots.map((s) => s.id)).toEqual(['files']);
  });
});

describe('every change is final when made (issue #1776)', () => {
  test('each change is written the moment it happens, with no Done', async () => {
    let writes = 0;
    const stop = onHomeChange(() => (writes += 1));
    enterLayoutEditor();
    const entry = writes;
    await addWidget('notes');
    expect(writes).toBeGreaterThan(entry);
    const afterAdd = writes;
    await removeWidget('stat-running');
    expect(writes).toBeGreaterThan(afterAdd);
    expect(layoutEditor.active).toBe(true);
    stop();
  });

  test('done only leaves the mode and keeps what is on screen', async () => {
    const before = JSON.stringify(homeLayout.state.layout);
    enterLayoutEditor();
    await addWidget('notes');
    finishLayoutEditor();
    expect(layoutEditor.active).toBe(false);
    expect(JSON.stringify(homeLayout.state.layout)).not.toBe(before);
    expect(placed()).toContain('notes');
  });

  test('a removed widget comes back from the drawer with a drag drop', async () => {
    enterLayoutEditor();
    await removeWidget('stat-running');
    expect(placed()).not.toContain('stat-running');
    expect(await dropWidget('stat-running', { kind: 'new', after: null })).toBe('landed');
    expect(placed()).toContain('stat-running');
  });

  test('nothing acts once the edit is over', async () => {
    expect(await addWidget('notes')).toBe(false);
    expect(await removeWidget('stat-running')).toBe(false);
    expect(placed()).toContain('stat-running');
  });
});

describe('a plugin panel view is one copy per page (#2379)', () => {
  test('a second copy is refused even when the first is a leftover cell of an earlier install', async () => {
    const { setPanels } = await import('../../lib/cplug-ui/panel-views.svelte');
    const row = (key: string) => ({ id: 'pillpanic', runtime: 'sidecar', enabled: true, state: 'active', name: 'Pill Panic', install_key: key,
      views: [{ name: 'game', surfaces: ['panel'] }] }) as never;
    setPanels([row('aaaaaaaa11')]);
    enterLayoutEditor();
    expect(addPanelWidget('pillpanic.game')).toBe(true);
    expect(placed().filter((id) => id.startsWith('pillpanic.game:'))).toEqual(['pillpanic.game:panel-aaaaaaaa']);
    setPanels([row('bbbbbbbb22')]);
    expect(addPanelWidget('pillpanic.game')).toBe(false);
    expect(placed().filter((id) => id.startsWith('pillpanic.game:'))).toEqual(['pillpanic.game:panel-aaaaaaaa']);
    setPanels([]);
  });
});
