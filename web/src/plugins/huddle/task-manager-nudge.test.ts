/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const api = vi.hoisted(() => ({ calls: [] as { path: string; init?: RequestInit }[], nudge: false }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: RequestInit) => {
      api.calls.push({ path, init });
      if (path.endsWith('/prefs')) {
        if (init?.method === 'PUT') api.nudge = JSON.parse(String(init.body)).nudge;
        return { list: '12', nudge: api.nudge };
      }
      if (path === '/cplugs/huddle') return { revision: 1, settings: {} };
      return {};
    },
  };
});

import { latestMessage } from './huddle-density';
import { actionOf } from './huddle-review';
import { getListNudge, setListNudge } from './task-list-prefs';
import TaskManagerProjectHead from './TaskManagerProjectHead.svelte';
import EditProjectModal from '../../lib/launchpad/EditProjectModal.svelte';
import { cplugEnablement } from '../host/enablement.svelte';
import type { TaskManagerMessage } from './huddle-model';

const msg = (id: number, extra: Partial<TaskManagerMessage> = {}): TaskManagerMessage => ({
  id, item_id: 1, author: 'claude', kind: 'info', text: `m${id}`, answered: false, created_at: id, seq: id, ...extra,
});

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  api.calls = [];
  api.nudge = false;
  cplugEnablement.enabled = {};
});

describe('thread and action vocabulary', () => {
  test('the row preview never shows a nudge line', () => {
    const thread = [msg(1), msg(2, { category: 'nudge', text: 'nudged 1 of 3' })];
    expect(latestMessage({ thread })?.id).toBe(1);
  });

  test('unstick is a known action', () => {
    expect(actionOf('unstick')).toBe('unstick');
  });

  test('the list prefs route is read and written with the project id', async () => {
    expect(await setListNudge(12, true)).toBe(true);
    expect(await getListNudge(12)).toBe(true);
    expect(api.calls[0]).toMatchObject({ path: '/cplugs/huddle/lists/12/prefs', init: { method: 'PUT', body: '{"nudge":true}' } });
  });
});

describe('the project header toggle', () => {
  const head = (nudge: boolean, onNudge?: (n: boolean) => void) =>
    mount(TaskManagerProjectHead, { target: document.body, props: { list: '12', heading: 'carnivore', count: 2, chips: [], folded: false, nudge, onNudge, onToggle: () => {} } });

  test('lit when on, dim when off, and a press asks for the other state', () => {
    const asked: boolean[] = [];
    app = head(true, (n) => asked.push(n));
    flushSync();
    const button = document.querySelector('[data-task-manager-project-nudge="12"]') as HTMLButtonElement;
    expect(button.dataset.on).toBe('on');
    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(button.getAttribute('aria-label')).toBeTruthy();
    expect(button.getAttribute('title')).toBe(button.getAttribute('aria-label'));
    button.click();
    expect(asked).toEqual([false]);
  });

  test('a list with no project gets no toggle', () => {
    app = head(false);
    flushSync();
    expect(document.querySelector('[data-task-manager-project-nudge]')).toBeNull();
  });
});

describe('the edit-project modal', () => {
  const modal = (close: (v: unknown) => void, projectId: number | null = 12) =>
    mount(EditProjectModal, { target: document.body, props: { projectName: 'carnivore', projectPath: '/p', projectId, close } });
  const settle = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); flushSync(); };

  test('the huddle section is hidden while the plugin is off', async () => {
    cplugEnablement.enabled = { huddle: false };
    app = modal(() => {});
    await settle();
    expect(document.querySelector('[data-edit-project-huddle]')).toBeNull();
    expect(api.calls.some((c) => c.path.endsWith('/prefs'))).toBe(false);
  });

  test('on: the box shows the stored value and the result carries the nudge only when changed', async () => {
    cplugEnablement.enabled = { huddle: true };
    api.nudge = true;
    const results: unknown[] = [];
    app = modal((v) => results.push(v));
    await settle();
    const box = document.querySelector('[data-edit-project-nudge]') as HTMLButtonElement;
    expect(box.getAttribute('aria-checked')).toBe('true');
    (document.querySelector('#edit-modal-save') as HTMLButtonElement).click();
    expect(results[0]).not.toHaveProperty('nudge');
    box.click();
    flushSync();
    (document.querySelector('#edit-modal-save') as HTMLButtonElement).click();
    expect(results[1]).toMatchObject({ nudge: false });
  });
});
