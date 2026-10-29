/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ calls: [] as Array<{ path: string; method: string }>, fail: false }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      server.calls.push({ path, method: init.method ?? 'GET' });
      if (/\/ticket$/.test(path)) {
        if (server.fail) throw new Error('nope');
        return { url: '/api/v1/cplugs/huddle/artifact-view/5.ab12cd34.9999999999.SIG', expires_in: 3600, title: 'Layout A' };
      }
      return {};
    },
  };
});

import TaskManagerArtifactDialog from './TaskManagerArtifactDialog.svelte';
import HuddleThread from './HuddleThread.svelte';
import { closeArtifact } from './task-manager-artifact.svelte';

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

const artifact = { id: 'ab12cd34', title: 'Layout A', description: 'two columns, dark', size: 2048 };
const item = {
  id: 5, list: 'all', text: 't', note: '', position: 1, created_by: 'joe', state: 'open', kind: '', number: 1, revision: 1,
  created_seq: 1, seq: 3, deleted: false, unread: false, group: null, status: 'question', section: 'question',
  thread: [
    { id: 8, item_id: 5, author: 'claude', kind: 'info', text: 'Layout A: two columns, dark', answered: false, created_at: 1, seq: 1, artifact },
    { id: 9, item_id: 5, author: 'claude', kind: 'question', text: 'Which layout do you want?', answered: false, created_at: 2, seq: 2 },
  ],
} as never;

describe('the artifact card and popout', () => {
  let apps: Array<ReturnType<typeof mount>> = [];

  beforeEach(() => {
    server.calls = [];
    server.fail = false;
  });

  afterEach(() => {
    closeArtifact();
    apps.forEach((a) => unmount(a));
    apps = [];
    document.body.innerHTML = '';
  });

  test('the thread draws a card (title, description, open) and not the message text', async () => {
    apps.push(mount(HuddleThread, { target: document.body, props: { item, closed: true } }));
    await settle();
    const card = document.querySelector('[data-task-manager-artifact="ab12cd34"]')!;
    expect(card.textContent).toContain('Layout A');
    expect(card.textContent).toContain('two columns, dark');
    expect(card.textContent).toContain('2 kb');
    expect(card.querySelector('[data-task-manager-artifact-open="ab12cd34"]')?.textContent?.trim()).toBe('open');
    expect(document.querySelector('[data-task-manager-message="8"] .hdt-text')?.textContent).not.toContain('Layout A: two columns');
  });

  test('a question the agent asks sits right under the card, in the thread order', async () => {
    apps.push(mount(HuddleThread, { target: document.body, props: { item, closed: true } }));
    await settle();
    const cardMessage = document.querySelector('[data-task-manager-message="8"]')!;
    const question = document.querySelector('[data-task-manager-message="9"]')!;
    expect(question.textContent).toContain('Which layout do you want?');
    expect(cardMessage.compareDocumentPosition(question) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(cardMessage.nextElementSibling).toBe(question);
  });

  test('open asks for a ticket and shows the page in a sandboxed frame WITHOUT allow-same-origin', async () => {
    apps.push(mount(HuddleThread, { target: document.body, props: { item, closed: true } }));
    apps.push(mount(TaskManagerArtifactDialog, { target: document.body }));
    expect(document.querySelector('[data-task-manager-artifact-frame]')).toBeNull();
    document.querySelector<HTMLButtonElement>('[data-task-manager-artifact-open="ab12cd34"]')!.click();
    await settle();
    expect(server.calls).toContainEqual({ path: '/cplugs/huddle/items/5/artifacts/ab12cd34/ticket', method: 'POST' });
    const frame = document.querySelector('iframe[data-task-manager-artifact-frame]')!;
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
    expect(frame.getAttribute('sandbox')).not.toContain('allow-same-origin');
    expect(frame.getAttribute('src')).toBe('/api/v1/cplugs/huddle/artifact-view/5.ab12cd34.9999999999.SIG');
    expect(frame.getAttribute('referrerpolicy')).toBe('no-referrer');
    expect(document.querySelector('[data-task-manager-artifact-dialog]')?.textContent).toContain('Layout A');
  });

  test('pop out is a plain new-window link to the same signed URL, and close removes the frame', async () => {
    apps.push(mount(HuddleThread, { target: document.body, props: { item, closed: true } }));
    apps.push(mount(TaskManagerArtifactDialog, { target: document.body }));
    document.querySelector<HTMLButtonElement>('[data-task-manager-artifact-open="ab12cd34"]')!.click();
    await settle();
    const pop = document.querySelector<HTMLAnchorElement>('[data-task-manager-artifact-popout]')!;
    expect(pop.getAttribute('href')).toBe('/api/v1/cplugs/huddle/artifact-view/5.ab12cd34.9999999999.SIG');
    expect(pop.getAttribute('target')).toBe('_blank');
    expect(pop.getAttribute('rel')).toBe('noopener noreferrer');
    document.querySelector<HTMLButtonElement>('[data-task-manager-artifact-close]')!.click();
    await settle();
    expect(document.querySelector('[data-task-manager-artifact-dialog]')).toBeNull();
    expect(document.querySelector('iframe')).toBeNull();
  });

  test('Escape closes the popout, and a failed ticket says so without a frame', async () => {
    server.fail = true;
    apps.push(mount(HuddleThread, { target: document.body, props: { item, closed: true } }));
    apps.push(mount(TaskManagerArtifactDialog, { target: document.body }));
    document.querySelector<HTMLButtonElement>('[data-task-manager-artifact-open="ab12cd34"]')!.click();
    await settle();
    expect(document.querySelector('[data-task-manager-artifact-failed]')).not.toBeNull();
    expect(document.querySelector('iframe')).toBeNull();
    document.querySelector('[data-task-manager-artifact-dialog]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle();
    expect(document.querySelector('[data-task-manager-artifact-dialog]')).toBeNull();
  });
});
