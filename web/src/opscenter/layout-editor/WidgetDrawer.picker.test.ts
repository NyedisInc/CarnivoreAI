/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const listing = vi.hoisted(() => ({
  data: [
    {
      session: { id: 'ses_a', working_dir: '/work/a' },
      session_row_id: 5,
      label: 'alpha',
      agent_family: 'claude',
    },
  ] as unknown[],
}));
vi.mock('../api/sessions.svelte', () => ({ sessions: listing }));
vi.mock('../../lib/browser/api.svelte', () => ({ browsers: { data: [] } }));
vi.mock('../../lib/item-settings/store.svelte', () => ({ isWidgetDisabled: () => false }));
vi.mock('../../lib/help/feature-media', () => ({
  fetchFeatureMediaBlob: () => Promise.reject(new Error('no server in this test')),
}));

import WidgetDrawer from './WidgetDrawer.svelte';
import { terminalLayout } from '../engine/layout.svelte';
import { editorSeams, enterLayoutEditor, finishLayoutEditor } from './editor.svelte';

const real = { ...editorSeams };
let app: ReturnType<typeof mount> | null = null;

const slots = (): string[] => terminalLayout.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));

beforeEach(() => {
  terminalLayout.resetAll();
  editorSeams.page = () => 'terminal';
  editorSeams.store = (p) => (p === 'terminal' ? terminalLayout : null);
  editorSeams.wide = () => true;
  enterLayoutEditor();
  app = mount(WidgetDrawer, { target: document.body, props: { store: terminalLayout, page: 'terminal' } });
  flushSync();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  finishLayoutEditor();
  Object.assign(editorSeams, real);
  document.body.replaceChildren();
});

test('picking a live session from the "session" row adds it as terminal:row:<id>, the engine\'s own slot', async () => {
  expect(slots()).not.toContain('terminal:row:5');

  document.querySelector<HTMLButtonElement>('[data-picker-entry="session"]')!.click();
  flushSync();
  const row = document.querySelector<HTMLButtonElement>('[data-picker-row="ses_a"]');
  expect(row, 'the fold lists the live, non-shell session').not.toBeNull();

  row!.click();
  await vi.waitFor(() => expect(slots()).toContain('terminal:row:5'));
  await vi.waitFor(() =>
    expect(document.querySelector('[data-picker-row="ses_a"]')?.getAttribute('aria-disabled')).toBe('true'),
  );
});

test('session, terminal and browser are three rows at the top, a hairline under them, each folding open to what it can add', () => {
  const group = document.querySelector('[data-window-picker]')!;
  const heads = [...group.querySelectorAll<HTMLButtonElement>('[data-le-card][data-picker-entry]')];
  expect(heads.map((one) => one.dataset['pickerEntry'])).toEqual(['session', 'terminal', 'browser']);
  expect(group.querySelector('.oc-seg')).toBeNull();
  const rule = group.querySelector('hr.le-windows__rule')!;
  expect(rule).not.toBeNull();
  expect(rule.previousElementSibling?.getAttribute('data-window-fold')).toBe('browser');
  const firstWidget = document.querySelector('.le-list [data-widget]')!;
  expect(rule.compareDocumentPosition(firstWidget) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(heads.every((one) => one.getAttribute('aria-expanded') === 'false')).toBe(true);
  expect(heads[0]!.textContent).toContain('1 live');
  expect(heads[2]!.textContent).toContain('0 live');
  heads[0]!.click();
  flushSync();
  expect(heads[0]!.getAttribute('aria-expanded')).toBe('true');
  expect(document.querySelector('#le-wfold-session [data-picker-row="ses_a"]')!.textContent).toContain('alpha');
  expect(document.querySelector('.le-list [data-widget]')).not.toBeNull();
  heads[2]!.click();
  flushSync();
  expect(heads[0]!.getAttribute('aria-expanded')).toBe('false');
  expect(document.querySelector('#le-wfold-browser')!.textContent).toContain('no live proxy browser right now');
  heads[2]!.click();
  flushSync();
  expect(document.querySelector('[id^="le-wfold-"]')).toBeNull();
});

test('the top "add widget" quick action is gone, on every page (issue #1043)', () => {
  expect(document.querySelector('[data-action="add-component"]')).toBeNull();
});
