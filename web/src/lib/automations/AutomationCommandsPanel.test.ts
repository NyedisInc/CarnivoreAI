/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const follow = vi.hoisted(() => ({ refresh: null as null | (() => void), topics: [] as readonly string[] }));
vi.mock('../resource-push/boot', () => ({
  resourcePush: () => ({
    pushOrPoll: (refresh: () => void, _ms: number, topics: readonly string[]) => {
      follow.refresh = refresh;
      follow.topics = topics;
      return () => {};
    },
  }),
}));

import AutomationCommandsPanel from './AutomationCommandsPanel.svelte';

const wire = (commands: string[]) => ({ commands, max_entries: 50, max_length: 500 });
let held: string[] = [];
let refuse: Error | null = null;
const fetcher = vi.fn(async (_path: string, init?: RequestInit) => {
  if (init?.method === 'PUT') {
    if (refuse) throw refuse;
    held = JSON.parse(String(init.body)).commands;
  }
  return wire(held);
});

let app: ReturnType<typeof mount> | null = null;
const settle = async () => {
  for (let i = 0; i < 6; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

beforeEach(async () => {
  held = [];
  refuse = null;
  fetcher.mockClear();
  app = mount(AutomationCommandsPanel, { target: document.body, props: { fetcher: fetcher as never } });
  await settle();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('it starts empty, adds a command by saving the whole list, and removes it again', async () => {
  expect(q('[data-automation-commands="empty"]').textContent).toContain('no commands are allowed yet');
  const input = q<HTMLInputElement>('[data-automation-commands="input"]');
  input.value = '/usr/bin/git pull --ff-only';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await settle();
  q('[data-automation-commands="add"]').click();
  await settle();
  expect(held).toEqual(['/usr/bin/git pull --ff-only']);
  expect(q('[data-automation-commands="list"]').textContent).toContain('/usr/bin/git pull --ff-only');
  expect(q<HTMLInputElement>('[data-automation-commands="input"]').value).toBe('');
  q('[data-automation-commands="remove"]').click();
  await settle();
  expect(held).toEqual([]);
  expect(document.querySelector('[data-automation-commands="list"]')).toBeNull();
});

test('a refusal is said and the typed text stays; the topic re-reads the list', async () => {
  refuse = new Error('a command is a program path');
  const input = q<HTMLInputElement>('[data-automation-commands="input"]');
  input.value = 'git pull';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await settle();
  q('[data-automation-commands="add"]').click();
  await settle();
  expect(q('[data-automation-commands="problem"]').textContent).toContain('program path');
  expect(q<HTMLInputElement>('[data-automation-commands="input"]').value).toBe('git pull');
  expect(follow.topics).toEqual(['automation_commands']);
  held = ['/bin/true'];
  follow.refresh!();
  await settle();
  expect(q('[data-automation-commands="list"]').textContent).toContain('/bin/true');
});
