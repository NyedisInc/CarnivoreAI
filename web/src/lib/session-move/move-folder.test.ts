/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const calls: { path: string; body: Record<string, unknown> }[] = [];
let projects: Record<string, unknown>[];
let plan: Record<string, unknown>;

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : {} });
    if (path === '/projects') return projects;
    if (path.endsWith('/move-folder')) {
      const body = JSON.parse(String(init?.body));
      return body.apply ? { ...plan, applied: true, done: { moved: 2 } } : plan;
    }
    throw new Error(`unexpected ${path}`);
  },
}));

import { auth } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';
import { formatBytes, sameDestination } from './move-api';
import { moveToFolderBridge } from './host';
import MoveFolderModal from './MoveFolderModal.svelte';

setLocale('en');

const PLAN = {
  session_uuid: 'u1', tmux_name: 'carnivore_x', source: '/home/alex', source_kind: 'temp', destination: '/p/app',
  destination_kind: 'project', project_id: 3, project_name: 'app', creates_folder: false, pane_state: 'exited',
  kills_live_pane: false, file_count: 2, total_bytes: 2048, left_behind: [], collisions: [], ok: true, refusals: [],
  applied: false, done: null,
};

const mounted: ReturnType<typeof mount>[] = [];
beforeEach(() => {
  auth.state = 'signed-in';
  calls.length = 0;
  projects = [{ id: 3, name: 'app', path: '/p/app' }, { id: null, name: 'config-only', path: '/p/c' }, { id: 4, name: 'old', path: '/p/o', archived_at: 'x' }];
  plan = { ...PLAN };
});
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});
const tick = async () => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };
const q = (sel: string) => document.querySelector<HTMLElement>(sel);
const moveCalls = () => calls.filter((c) => c.path.endsWith('/move-folder'));

async function open() {
  const root = document.createElement('div');
  document.body.append(root);
  const onClose = vi.fn();
  mounted.push(mount(MoveFolderModal, { target: root, props: { uuid: 'u1', name: 'api', onClose } }));
  await tick();
  return { onClose };
}

async function pickProject() {
  const select = q('[data-move="project"]') as HTMLSelectElement;
  select.value = '3';
  select.dispatchEvent(new Event('change', { bubbles: true }));
  await tick();
}

async function press(which: string) {
  (q(`[data-move="${which}"]`) as HTMLButtonElement).click();
  await tick();
}

describe('the move dialog', () => {
  test('offers stored, unarchived projects only, and nothing can move before a check', async () => {
    await open();
    const options = [...document.querySelectorAll('[data-move="project"] option')].map((o) => o.textContent);
    expect(options).toEqual(['choose a project', 'app']);
    expect((q('[data-move="go"]') as HTMLButtonElement).disabled).toBe(true);
    expect((q('[data-move="check"]') as HTMLButtonElement).disabled).toBe(true);
    await pickProject();
    expect((q('[data-move="check"]') as HTMLButtonElement).disabled).toBe(false);
    expect((q('[data-move="go"]') as HTMLButtonElement).disabled).toBe(true);
    expect(moveCalls()).toEqual([]);
  });

  test('check plans with apply false, shows the plan, and the move then applies it', async () => {
    await open();
    await pickProject();
    await press('check');
    expect(moveCalls()).toEqual([{ path: '/sessions/u1/move-folder', body: { project_id: 3, apply: false, confirm_restart_live: false } }]);
    expect(q('[data-move="from"]')?.textContent).toContain('/home/alex');
    expect(q('[data-move="to"]')?.textContent).toContain('/p/app');
    expect(q('[data-move="files"]')?.textContent).toContain('2 carried, 2.0 kb');
    expect(q('[data-move="live"]')).toBeNull();
    await press('go');
    expect(moveCalls()[1]?.body).toEqual({ project_id: 3, apply: true, confirm_restart_live: false });
    expect(q('[data-move="done"]')?.textContent).toContain('moved to /p/app');
  });

  test('a refused plan shows the server sentence and never enables the move', async () => {
    plan = { ...PLAN, ok: false, collisions: ['notes.md'], refusals: [{ code: 'collision', message: 'the destination already has notes.md' }] };
    await open();
    await pickProject();
    await press('check');
    expect(q('[data-move="refusal"]')?.textContent).toBe('the destination already has notes.md');
    expect(q('[data-move="collisions"]')?.textContent).toContain('notes.md');
    expect((q('[data-move="go"]') as HTMLButtonElement).disabled).toBe(true);
    await press('go');
    expect(moveCalls().filter((c) => c.body.apply === true)).toEqual([]);
  });

  test('a running agent needs the arm box, and only the ticked box sends confirm_restart_live', async () => {
    plan = { ...PLAN, pane_state: 'live', kills_live_pane: true };
    await open();
    await pickProject();
    await press('check');
    expect(q('[data-move="live"]')).not.toBeNull();
    expect(q('[data-move="go"]')?.textContent).toBe('stop and move');
    expect(q('[data-move="go"]')?.getAttribute('data-btn') === 'danger').toBe(true);
    expect((q('[data-move="go"]') as HTMLButtonElement).disabled).toBe(true);
    await press('go');
    expect(moveCalls().filter((c) => c.body.apply === true)).toEqual([]);
    (q('[data-move="arm"]') as HTMLButtonElement).click();
    await tick();
    expect((q('[data-move="go"]') as HTMLButtonElement).disabled).toBe(false);
    await press('go');
    expect(moveCalls().at(-1)?.body).toEqual({ project_id: 3, apply: true, confirm_restart_live: true });
  });

  test('changing the destination drops the plan so a stale plan never runs', async () => {
    await open();
    await pickProject();
    await press('check');
    expect((q('[data-move="go"]') as HTMLButtonElement).disabled).toBe(false);
    (document.querySelector('input[data-choice="folder"]') as HTMLInputElement).click();
    await tick();
    expect(q('[data-move="plan"]')).toBeNull();
    expect((q('[data-move="go"]') as HTMLButtonElement).disabled).toBe(true);
  });

  test('a new folder is sent as new_folder, trimmed', async () => {
    await open();
    (document.querySelector('input[data-choice="folder"]') as HTMLInputElement).click();
    await tick();
    const field = q('[data-move="folder"]') as HTMLInputElement;
    field.value = '  /Users/me/app  ';
    field.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    await press('check');
    expect(moveCalls()[0]?.body).toEqual({ new_folder: '/Users/me/app', apply: false, confirm_restart_live: false });
  });

  test('escape closes the dialog', async () => {
    const { onClose } = await open();
    q('[data-move-modal]')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe('helpers and the host', () => {
  test('sameDestination compares project and folder destinations', () => {
    expect(sameDestination({ project_id: 1 }, { project_id: 1 })).toBe(true);
    expect(sameDestination({ project_id: 1 }, { project_id: 2 })).toBe(false);
    expect(sameDestination({ new_folder: '/a' }, { project_id: 1 })).toBe(false);
    expect(sameDestination(null, { project_id: 1 })).toBe(false);
  });

  test('formatBytes reads as short sizes', () => {
    expect(formatBytes(12)).toBe('12 b');
    expect(formatBytes(1536)).toBe('1.5 kb');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 mb');
  });

  test('the host mounts the dialog into its container and closes it', async () => {
    const holder = document.createElement('div');
    holder.id = 'move-folder-modal';
    document.body.append(holder);
    expect(moveToFolderBridge.open({ sessionUuid: 'u1', name: 'api' })).toBe(true);
    await tick();
    expect(holder.querySelector('[data-move-modal]')).not.toBeNull();
    moveToFolderBridge.close();
    expect(holder.querySelector('[data-move-modal]')).toBeNull();
  });
});
