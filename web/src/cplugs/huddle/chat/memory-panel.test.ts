/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const server = vi.hoisted(() => ({
  text: '# notes\n',
  backups: [] as Array<{ id: string; at: string }>,
  writes: [] as Array<{ method: string; path: string; body: unknown }>,
}));

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      if (path === '/swarm/agents/7/memory') {
        return [{ path: 'MEMORY.md', title: 'MEMORY.md', state: null }, { path: 'facts/f_0123456789ab.md', title: 'restart after a swap', state: 'live' }];
      }
      if (method !== 'GET') {
        const body = JSON.parse(String(init.body));
        server.writes.push({ method, path, body });
        if (method === 'PUT') {
          server.backups = [{ id: '20261028T030000000000Z', at: '2026-10-28T03:00:00+00:00' }, ...server.backups];
          server.text = body.text;
        }
      }
      return { path: 'MEMORY.md', text: server.text, backups: server.backups };
    },
  };
});

import MemoryPanel from './MemoryPanel.svelte';

let app: object | null = null;

beforeEach(() => {
  Object.assign(server, { text: '# notes\n', backups: [], writes: [] });
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
});

function type(value: string): void {
  const box = document.querySelector('[data-memory-text]') as HTMLTextAreaElement;
  box.value = value;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
}

const button = (key: string): HTMLButtonElement => document.querySelector(`[data-memory-${key}]`) as HTMLButtonElement;

test('save backs up on the server, undo discards then restores, an earlier version restores by id', async () => {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(MemoryPanel, { target: document.getElementById('host') as HTMLElement, props: { agentId: 7, name: 'Rook', onclose: () => {} } });
  await vi.waitFor(() => expect((document.querySelector('[data-memory-text]') as HTMLTextAreaElement | null)?.value).toBe('# notes\n'));
  const files = [...document.querySelectorAll('[data-memory-file] option')].map((o) => o.textContent);
  expect(files).toEqual(['MEMORY.md', 'restart after a swap']);
  expect(button('save').disabled).toBe(true);
  expect(button('undo').disabled).toBe(true);

  type('# notes\nedited\n');
  expect(button('save').disabled).toBe(false);
  button('undo').click();
  flushSync();
  expect((document.querySelector('[data-memory-text]') as HTMLTextAreaElement).value).toBe('# notes\n');
  expect(server.writes).toEqual([]);

  type('# notes\nedited\n');
  button('save').click();
  await vi.waitFor(() => expect(button('save').disabled).toBe(true));
  expect(server.writes[0]).toEqual({ method: 'PUT', path: '/swarm/agents/7/memory/file', body: { path: 'MEMORY.md', text: '# notes\nedited\n' } });

  await vi.waitFor(() => expect(button('undo').disabled).toBe(false));
  button('undo').click();
  await vi.waitFor(() => expect(server.writes).toHaveLength(2));
  expect(server.writes[1]).toEqual({ method: 'POST', path: '/swarm/agents/7/memory/restore', body: { path: 'MEMORY.md' } });

  await vi.waitFor(() => expect((document.querySelector('[data-memory-revert]') as HTMLSelectElement).disabled).toBe(false));
  const revert = document.querySelector('[data-memory-revert]') as HTMLSelectElement;
  revert.value = '20261028T030000000000Z';
  revert.dispatchEvent(new Event('change', { bubbles: true }));
  await vi.waitFor(() => expect(server.writes).toHaveLength(3));
  expect(server.writes[2].body).toEqual({ path: 'MEMORY.md', backup_id: '20261028T030000000000Z' });
});
