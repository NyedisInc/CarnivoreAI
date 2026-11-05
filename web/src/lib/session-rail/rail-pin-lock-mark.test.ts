/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ label: 'api', session_row_id: 7, session: { id: 'ses_1' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('./test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { BOTTOM_FIELD, follow, keyIn, mountRails, unmountRails } from './rail-test-harness';
import { railSlideout } from './slideout.svelte';
import { fakeActive } from './test-support.svelte';
import { panelPins } from '../widget-bars/panel-pins.svelte';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';

const marks = (): number => document.querySelectorAll('[data-widget-head] [data-head-lock]').length;

beforeEach(() => {
  localStorage.clear();
  panelPins.reload();
  fakeActive.id = 'ses_1';
  mountRails();
  follow(BOTTOM_FIELD, {
    v: 2,
    ratio: 0.5,
    sections: [{ items: [{ widget: 'core.files', options: { show_header: true } }] }, { items: [{ widget: 'core.notes', options: { show_header: true } }] }],
  });
});
afterEach(() => {
  layoutEditor.active = false;
  railSlideout.close();
  unmountRails();
});

describe('the lock mark follows the real pin', () => {
  test('an unpinned tab draws none; pinning the tab through the pin store puts the mark in its header alone', () => {
    keyIn('bottom', 'core.files').click();
    flushSync();
    expect(document.querySelectorAll('[data-widget-head]').length).toBeGreaterThan(0);
    expect(marks()).toBe(0);
    panelPins.pin('bottom', 'core.notes', 7);
    flushSync();
    expect(marks()).toBe(1);
    const lockedHead = document.querySelector('[data-widget-head] [data-head-lock]')!.closest('[data-widget-head]')!;
    expect(lockedHead.textContent).toContain('notes');
    panelPins.unpin('bottom', 'core.notes');
    flushSync();
    expect(marks()).toBe(0);
  });

  test('edit layout keeps the mark: the pinned tab is still scoped to its agent there', () => {
    keyIn('bottom', 'core.files').click();
    panelPins.pin('bottom', 'core.notes', 7);
    flushSync();
    layoutEditor.active = true;
    flushSync();
    expect(panelPins.pinnedRow('bottom', 'core.notes')).toBe(7);
    expect(marks()).toBe(1);
    layoutEditor.active = false;
    flushSync();
    expect(marks()).toBe(1);
  });
});
