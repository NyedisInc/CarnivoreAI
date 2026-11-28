/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ChatAvatar from './ChatAvatar.svelte';
import type { BurstParty } from './chat-model';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; });

test('a party the node looks cannot find draws a resting character, not the hollow unknown face', () => {
  const party: BurstParty = { key: 'a:80', dir: 'in', path: [{ kind: 'agent', name: 'Ui-Fixes', agent_id: 80 }], agentId: 80,
                              sessionUuid: 'eb900bd3-15e8-b753-18d7-924a425e5624', owner: false };
  app = mount(ChatAvatar, { target: document.body, props: { party, name: 'Ui-Fixes', looks: null } });
  flushSync();
  const face = document.querySelector('[data-state]');
  expect(face).not.toBeNull();
  expect(face?.getAttribute('data-state')).toBe('idle');
});
