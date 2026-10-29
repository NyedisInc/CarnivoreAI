/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TaskManagerSteps from './TaskManagerSteps.svelte';
import * as store from './task-manager-steps.svelte';
import { taskManagerSteps, stepsOfItem } from './task-manager-steps.svelte';
import { parseSteps, type StepsEntry } from './task-manager-steps';

const entry: StepsEntry = {
  tasks: [
    { id: '1', subject: 'plan', active_form: null, status: 'completed' },
    { id: '2', subject: 'run tests', active_form: 'running tests', status: 'in_progress' },
    { id: '3', subject: 'ship', active_form: null, status: 'pending' },
  ],
  counts: { pending: 1, in_progress: 1, completed: 1 },
};

let host: HTMLElement | null = null;
let handle: ReturnType<typeof mount> | null = null;

function show(props: { entry: StepsEntry | null; label?: string; open?: boolean }): HTMLElement {
  host = document.createElement('div');
  document.body.append(host);
  handle = mount(TaskManagerSteps, { target: host, props });
  flushSync();
  return host;
}

afterEach(() => {
  if (handle) unmount(handle);
  host?.remove();
  handle = host = null;
  taskManagerSteps.byList = {};
});

describe('TaskManagerSteps', () => {
  test('shows the compact line and expands into the checklist', () => {
    const el = show({ entry });
    expect(el.querySelector('[data-task-manager-steps-count]')?.textContent).toBe('1 of 3');
    expect(el.querySelector('.hds-now')?.textContent).toContain('running tests');
    expect(el.querySelector('[data-task-manager-steps-list]')).toBeNull();
    el.querySelector<HTMLButtonElement>('.hds-fold')!.click();
    flushSync();
    expect(el.querySelectorAll('.oc-tsk-row').length).toBe(3);
  });

  test('draws nothing without a checklist, and opens at once on a claimed item when asked', () => {
    expect(show({ entry: null }).querySelector('[data-task-manager-steps]')).toBeNull();
    unmount(handle!);
    host!.remove();
    expect(show({ entry, open: true }).querySelectorAll('.oc-tsk-row').length).toBe(3);
  });

  test('the store looks up a claimed item from a parsed body', () => {
    taskManagerSteps.byList = parseSteps({ lists: { '12': { items: { '7': entry } } } });
    expect(stepsOfItem('12', 7)).not.toBeNull();
    expect(stepsOfItem('12', 8)).toBeNull();
  });

  test('an unclaimed working session yields no line under the project: a body that still carries sessions shows none', () => {
    taskManagerSteps.byList = parseSteps({ lists: { '12': { items: {}, sessions: [{ session_id: 'ses_2', label: 'a', ...entry }] } } });
    expect(taskManagerSteps.byList).toEqual({});
    expect('stepsOfSessions' in store).toBe(false);
    taskManagerSteps.byList = parseSteps({ lists: { '12': { items: { '7': entry }, sessions: [{ session_id: 'ses_2', label: 'a', ...entry }] } } });
    expect(Object.keys(taskManagerSteps.byList['12'])).toEqual(['items']);
  });
});
