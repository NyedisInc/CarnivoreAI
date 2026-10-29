/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

const stub = vi.hoisted(() => ({ listProjectChoices: vi.fn(), listClaudeLogins: vi.fn(), listAnthropicKeys: vi.fn() }));
vi.mock('./api', () => stub);

import AgentBuilder from './AgentBuilder.svelte';
import { blankAgent, toolsFor } from './agent-defaults';

let app: ReturnType<typeof mount> | null = null;
let current: Record<string, unknown> = blankAgent();
const settle = async (): Promise<void> => {
  for (let i = 0; i < 8; i++) await tick();
  flushSync();
};
const rows = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('[data-agent-levels] [role="radio"]')];

beforeEach(async () => {
  Object.values(stub).forEach((fn) => fn.mockReset());
  stub.listProjectChoices.mockResolvedValue([{ name: 'site', folder: '/x/site' }]);
  stub.listClaudeLogins.mockResolvedValue([]);
  stub.listAnthropicKeys.mockResolvedValue([]);
  current = blankAgent();
  const box = new SvelteMap<string, unknown>([['target', current]]);
  const props = {
    get target() { return box.get('target') as Record<string, unknown>; },
    set target(next: Record<string, unknown>) { current = next; box.set('target', next); },
  };
  app = mount(AgentBuilder, { target: document.body, props: props as never });
  await settle();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('three rows, read only checked, under one group named for what it asks', () => {
  expect(rows()).toHaveLength(3);
  expect(rows().map((r) => r.getAttribute('aria-checked'))).toEqual(['true', 'false', 'false']);
  const group = document.querySelector('[data-agent-levels] [role="radiogroup"]')!;
  expect(group.getAttribute('aria-labelledby')).toBeTruthy();
});

test('choosing edits swaps the tool list; choosing unattended asks for the phrase', async () => {
  rows()[1]!.click();
  await settle();
  expect(current.permission).toBe('edits_in_folder');
  expect(current.tools).toEqual(toolsFor('edits_in_folder'));
  expect(document.querySelector('[data-agent-warning]')).toBeNull();
  rows()[2]!.click();
  await settle();
  expect(current.permission).toBe('unattended');
  expect(document.querySelector('[data-agent-warning]')).not.toBeNull();
  expect(document.querySelector('[data-agent-phrase]')).not.toBeNull();
  rows()[0]!.click();
  await settle();
  expect(current.permission).toBe('read_only');
  expect(current.acknowledge_unattended).toBeUndefined();
});

test('model and effort ride the target only when set; "default" sends neither', async () => {
  const model = document.querySelector<HTMLInputElement>('[data-agent-model]')!;
  const effort = document.querySelector<HTMLSelectElement>('[data-agent-effort]')!;
  expect(model.placeholder).toBe('default');
  expect([...effort.options].map((o) => o.textContent)).toEqual(['default', 'low', 'medium', 'high', 'xhigh', 'max']);
  expect('model' in current).toBe(false);
  expect('effort' in current).toBe(false);
  model.value = '  opus  ';
  model.dispatchEvent(new Event('change', { bubbles: true }));
  effort.value = 'xhigh';
  effort.dispatchEvent(new Event('change', { bubbles: true }));
  await settle();
  expect(current.model).toBe('opus');
  expect(current.effort).toBe('xhigh');
  model.value = '';
  model.dispatchEvent(new Event('change', { bubbles: true }));
  effort.value = '';
  effort.dispatchEvent(new Event('change', { bubbles: true }));
  await settle();
  expect('model' in current).toBe(false);
  expect('effort' in current).toBe(false);
});

test('an existing agent opens with both filled', async () => {
  unmount(app!);
  document.body.innerHTML = '';
  app = mount(AgentBuilder, { target: document.body, props: { target: { ...blankAgent(), model: 'sonnet', effort: 'high' } } as never });
  await settle();
  expect(document.querySelector<HTMLInputElement>('[data-agent-model]')!.value).toBe('sonnet');
  expect(document.querySelector<HTMLSelectElement>('[data-agent-effort]')!.value).toBe('high');
});
