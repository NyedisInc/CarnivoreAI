/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import Cell from './Cell.svelte';
import { metaFor } from '../../engine/meta';
import type { SlotId } from '../../engine/types';
import { setSkillsDrawer, skillsDrawerOpen, toggleSkillsDrawer } from '../../../lib/session-skills/drawer.svelte';
import { setLocale } from '../../../lib/i18n/index.svelte';

vi.mock('./client', () => ({ startLiveTerminal: () => null }));
vi.mock('./actions', () => ({
  registerTerminalActions: () => () => {},
  terminalAction: (slot: string, action: string) => {
    if (action === 'skills') toggleSkillsDrawer(slot);
  },
  toolShowing: () => false,
}));
vi.mock('./theme', () => ({ bindTerminalTheme: () => () => {} }));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    sessions: {
      get data() {
        return [{
          session: { id: 'ses_k' }, tmux_session: 'cloude_k', pinned_theme: null, agent_type: 'claude',
          skills_fired: 3, skill_last: { name: 'sme', at: null },
        }];
      },
      status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
  };
});
vi.mock('../../api/auth.svelte', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path.endsWith('/skill-fires')) return { state: 'measured', fired: 0, recent: [] };
      if (path.endsWith('/skills')) {
        return {
          state: 'ok', family: 'claude', working_dir: '/work/lab', budget_tokens_est: 40,
          skills: [{
            name: 'sme', location_id: 'personal-claude:sme', scope: 'personal', state: 'on', state_source: null,
            model_sees: true, reason: null, description_tokens_est: 40, tokens_est: 40, shadowed_by: null,
          }],
        };
      }
      return { state: 'none', suggestions: [] };
    },
  };
});
vi.mock('../../api/events.svelte', () => ({ subscribe: () => () => {} }));

setLocale('en');
const SLOT = 'terminal:ses_k';
const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  (HTMLElement.prototype as { hidePopover?: () => void }).hidePopover = () => {};
  setSkillsDrawer(SLOT, false);
});
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
});

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}

async function render(width = 900): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(Cell, { target, props: { width, height: 400, meta: metaFor(SLOT as SlotId), instance: SLOT } }));
  await settle();
  return target;
}

test('the skills icon toggles a drawer inside the cell, which lists the skills; Escape closes it', async () => {
  const cell = await render();
  const entry = cell.querySelector('.cell-tools [data-tool="skills"], .cell-options [data-tool="skills"]') as HTMLElement;
  expect(entry).not.toBeNull();
  expect(cell.querySelector('[data-session-skills]')).toBeNull();

  entry.click();
  await settle();
  const drawer = cell.querySelector('[data-session-skills]') as HTMLElement;
  expect(drawer, 'the drawer is inside the cell, not a popup on the body').not.toBeNull();
  expect(drawer.closest('.oc-tl-stage')).not.toBeNull();
  expect(drawer.classList.contains('sal-panel--full')).toBe(false);
  expect(drawer.querySelector('[data-session-skill="sme"]')).not.toBeNull();
  expect(drawer.closest('.oc-tl-body')).toBeNull();

  drawer.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await settle();
  expect(cell.querySelector('[data-session-skills]')).toBeNull();
  expect(skillsDrawerOpen(SLOT)).toBe(false);

  entry.click();
  await settle();
  expect(cell.querySelector('[data-session-skills]')).not.toBeNull();
  entry.click();
  await settle();
  expect(cell.querySelector('[data-session-skills]')).toBeNull();
});

test('a narrow cell gets the full-width drawer', async () => {
  setSkillsDrawer(SLOT, true);
  const cell = await render(400);
  expect(cell.querySelector('[data-session-skills]')?.classList.contains('sal-panel--full')).toBe(true);
});

test('no skill chip is drawn in the cell, whatever the row carries', async () => {
  setSkillsDrawer(SLOT, true);
  const cell = await render();
  expect(cell.querySelector('[data-skill-fires-session-id], .timer-chip')).toBeNull();
  expect(cell.textContent).not.toContain('3 skills');
});
