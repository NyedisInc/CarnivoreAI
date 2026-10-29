/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const NOW = Math.floor(Date.now() / 1000);
const reads: string[] = [];
let sendsAnswer: 'rows' | 'fail' = 'rows';

vi.mock('../../api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (path: string) => {
    reads.push(path);
    if (path.startsWith('/cplugs/huddle/sent')) {
      if (sendsAnswer === 'fail') throw new Error('down');
      return {
        now: NOW,
        sends: [
          { key: 'm:9', kind: 'reply', at: NOW - 120, text: 'looks good\nship it', list: '18', list_name: 'carnivore', session: 'Agent - Carnivore', item: { id: 7, title: 'fix the login' }, board: null,
            tell: { state: 'told', label: 'carnivore', at: NOW - 60, due_at: null, reason: null } },
          { key: 'm:8', kind: 'round', at: NOW - 300, text: 'round 2', list: '18', list_name: 'carnivore', item: null, board: { slug: 'b', round: 'n2' },
            tell: { state: 'queued', label: null, at: null, due_at: NOW + 8, reason: null } },
          { key: 'e:3', kind: 'add', at: NOW - 900, text: 'a new thing', list: '18', list_name: 'carnivore', item: null, board: null,
            tell: { state: 'not_sent', label: null, at: null, due_at: null, reason: 'agent gone' } },
        ],
      };
    }
    return null;
  },
}));
vi.mock('../../api/events.svelte', () => ({ subscribe: () => () => {} }));

import SentList from './SentList.svelte';
import { setLocale } from '../../../lib/i18n/index.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { META } from '../../engine/meta';
import { putEntry, resetStore } from '../../../lib/outbox/outbox-store';
import { stopOutbox } from '../../../lib/outbox/outbox';
import { WAIT_FOR_TRIGGER, type OutboxEntry } from '../../../lib/outbox/outbox-model';

setLocale('en');
const apps: ReturnType<typeof mount>[] = [];

function kept(id: string, over: Partial<OutboxEntry> = {}): OutboxEntry {
  return {
    id, kind: 'reply', request: { method: 'POST', path: '/x', body: {} }, ageField: null, after: null,
    label: { text: 'the words the owner typed and must not lose', where: 'fix the login', list: '18', item: 7 },
    created_at: Date.now() - 5000, attempts: 1, next_at: Date.now() + 20000, state: 'pending', error: null, lease: null, ...over,
  };
}

beforeEach(() => {
  reads.length = 0;
  sendsAnswer = 'rows';
  globalThis.localStorage?.clear();
  resetStore();
  stopOutbox();
  cplugEnablement.enabled = {};
});

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  stopOutbox();
});

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function render(width = 600): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(SentList, { target, props: { width, height: 300, meta: META['developer'], instance: 'developer', page: 'home' } as never }));
  await settle();
  return target;
}

describe('the sent tab', () => {
  test('a refused copy renders at the top with retry, copy and discard; a waiting one has no discard', async () => {
    putEntry(kept('wait-0001-aaaa'));
    putEntry(kept('fail-0001-bbbb', { state: 'failed', next_at: WAIT_FOR_TRIGGER, error: { status: 422, code: 'task_manager_invalid', message: 'text too long' } }));
    const target = await render();
    const rows = [...target.querySelectorAll('[data-outbox-row]')];
    expect(rows.map((r) => r.getAttribute('data-outbox-row'))).toEqual(['fail-0001-bbbb', 'wait-0001-aaaa']);
    const keys = (row: Element): string[] => [...row.querySelectorAll('[data-outbox-key]')].map((k) => k.getAttribute('data-outbox-key') as string);
    expect(keys(rows[0] as Element)).toEqual(['retry', 'copy', 'discard']);
    expect(keys(rows[1] as Element)).toEqual(['retry', 'copy']);
    expect(rows[0]?.textContent).toContain('not sent: text too long');
    expect(rows[1]?.textContent).toContain('retrying, next try');
    expect(target.querySelector('[data-sent-summary]')?.textContent).toBe('2 in this browser, 1 not sent');
    expect(target.querySelector('.oc-rc > .oc-rc-bar')).not.toBeNull();
  });

  test('the server rows say where each send stands with the agent', async () => {
    const target = await render();
    const text = [...target.querySelectorAll('[data-sent-chart] .oc-table-row')].map((row) => row.textContent?.replace(/\s+/g, ' ').trim() ?? '');
    expect(text[0]).toContain('reply: looks good ship it');
    expect(text[0]).toContain('fix the login');
    expect(text[0]).toContain('told carnivore 1m ago');
    expect(text[1]).toContain('telling in');
    const sessions = [...target.querySelectorAll('[data-sent-chart] [data-sent-session]')].map((c) => c.textContent);
    expect(sessions).toEqual(['Agent - Carnivore', '', '']);
    expect(text[2]).toContain('not told: agent gone');
    expect(target.querySelector('[data-sent-chart] [data-mark="error"]')).not.toBeNull();
  });

  test('the Task Manager off keeps the local copies and says why the list is missing', async () => {
    cplugEnablement.enabled = { huddle: false } as never;
    putEntry(kept('wait-0002-cccc'));
    const target = await render();
    expect(target.querySelector('[data-outbox-row]')).not.toBeNull();
    expect(target.querySelector('[data-sent-huddle-off]')?.textContent).toBe('the task manager is off');
    expect(reads.some((p) => p.startsWith('/cplugs/huddle/sent'))).toBe(false);
  });

  test('a failed read says so in coral', async () => {
    sendsAnswer = 'fail';
    const target = await render();
    expect(target.querySelector('[data-sent-note="unknown"]')?.getAttribute('data-tone')).toBe('bad');
  });
});
