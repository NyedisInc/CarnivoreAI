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

function headOf(widget: string): string[] {
  const section = document.querySelector(`[data-rail-body="${widget}"]`)?.closest('.rail-out__section');
  const head = section?.querySelector('[data-widget-head]');
  if (!head) return ['no-head'];
  const close = head.querySelector('[data-head-close]');
  return [
    head.querySelector('h2.oc-frame-name') ? 'title' : 'no-title',
    close?.previousElementSibling?.getAttribute('role') === 'separator' ? 'divider' : 'no-divider',
    close ? 'close' : 'no-close',
  ];
}

beforeEach(() => {
  localStorage.clear();
  panelPins.reload();
  fakeActive.id = 'ses_1';
  mountRails();
  follow(BOTTOM_FIELD, {
    v: 2,
    ratio: 0.5,
    sections: [
      { items: [{ widget: 'core.terminal', target: 'row:999' }] },
      { items: [{ widget: 'core.notes', options: { show_header: true } }] },
    ],
  });
});
afterEach(() => {
  railSlideout.close();
  unmountRails();
});

describe('a bottom panel with a terminal beside another widget', () => {
  test('both sections wear the standard header: title, hairline before close, close; the terminal body is not headless', () => {
    keyIn('bottom', 'core.terminal@row:999').click();
    flushSync();
    expect(headOf('core.notes')).toEqual(['title', 'divider', 'close']);
    expect(headOf('core.terminal')).toEqual(['title', 'divider', 'close']);
    expect(document.querySelector('[data-rail-body="core.terminal"]')?.hasAttribute('data-headless')).toBe(false);
  });
});
