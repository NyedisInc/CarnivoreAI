/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return {
    ...real,
    sessions: { data: [{ session_row_id: 7, project_id: 4, label: 'alpha', agent_family: 'claude', tmux_session: 'carnivore_alpha', session: { id: 'ses_1', working_dir: '/w' } }], status: 'ok', refresh: vi.fn() },
    primarySessionId: () => 'ses_1',
  };
});
vi.mock('../../lib/active-terminal', async () => {
  const { fakeActive: active } = await import('../../../lib/session-rail/test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('./actions', () => ({ registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false }));
vi.mock('../../../lib/terminal-search/cell-search', () => ({ cellSearchFor: () => null }));
vi.mock('../registry', async () => {
  const { default: TerminalHeadProbe } = await import('../../shell/fixtures/TerminalHeadProbe.svelte');
  const { ScopeProbe } = await import('../../../lib/session-rail/test-support.svelte');
  return { entryFor: (slot: string) => ({ component: slot.startsWith('terminal') ? TerminalHeadProbe : ScopeProbe }) };
});

import { BOTTOM_FIELD, follow, keyIn, mountRails, unmountRails } from '../../../lib/session-rail/rail-test-harness';
import { railSlideout } from '../../../lib/session-rail/slideout.svelte';
import { fakeActive } from '../../../lib/session-rail/test-support.svelte';
import { panelPins } from '../../../lib/widget-bars/panel-pins.svelte';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';
import { setLocale } from '../../../lib/i18n/index.svelte';

setLocale('en');
installPopoverPolyfill();

function controlsOf(widget: string): string[] {
  const head = document.querySelector(`[data-rail-body="${widget}"]`)?.closest('.rail-out__section')?.querySelector('[data-widget-head]');
  if (!head) return ['no-head'];
  const close = head.querySelector('[data-head-close]');
  return [
    head.querySelector('[data-corner]') ? 'icon-menu' : null,
    head.querySelector('h2.oc-frame-name') ? 'title' : null,
    head.querySelector('[data-tool="overflow"]') ? 'kebab' : null,
    close?.previousElementSibling?.getAttribute('role') === 'separator' ? 'divider' : null,
    close ? 'close' : null,
  ].filter((one): one is string => one !== null);
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
  keyIn('bottom', 'core.terminal@row:999').click();
  flushSync();
});
afterEach(() => {
  railSlideout.close();
  unmountRails();
});

describe('the terminal header beside the standard header', () => {
  test('the terminal draws every control the standard header does, plus its kebab, all inside the one header', () => {
    const standard = controlsOf('core.notes');
    expect(standard).toEqual(['icon-menu', 'title', 'divider', 'close']);
    expect(controlsOf('core.terminal')).toEqual(['icon-menu', 'title', 'kebab', 'divider', 'close']);
  });

  test('the kebab opens the terminal menu, ending in the session actions fold-out', () => {
    const kebab = document.querySelector<HTMLButtonElement>('[data-widget-head] [data-tool="overflow"]');
    expect(kebab?.getAttribute('aria-haspopup')).toBe('menu');
    expect(document.querySelectorAll('[data-rail-body="core.terminal"]')).toHaveLength(1);
    expect(document.querySelector('.cell-options [data-tool="actions"]')).not.toBeNull();
  });
});
