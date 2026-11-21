/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const msg = (id: number, item: number, kind: string, text: string, extra: Record<string, unknown> = {}) =>
  ({ id, item_id: item, author: 'claude', kind, text, answered: false, created_at: id, seq: id, ...extra });

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: 7, status: 'question', section: 'question', ...extra,
});

const server = vi.hoisted(() => ({ items: [] as unknown[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'status', density: 'normal' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 2, open: 2, review: 0, questions: 2, claude_seq: 0, unread: 0 }] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) {
        return { list: 'all', revision: 9, cursor: 9, groups: [{ id: 7, list: 'all', name: 'huddle', position: 0, folded: false }], items: server.items };
      }
      return {};
    },
  };
});

import { refreshTaskManager, huddle } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { statusFolds } from './task-manager-status-folds.svelte';
import { askParts, hasNumberedAsk } from './task-manager-posts';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

const ASKED = () => msg(10, 1, 'question', 'two ways to install\n\n1. a or b?\n2. tonight?', { context: 'two ways to install', questions: ['a or b?', 'tonight?'] });

beforeEach(() => {
  statusFolds.choices = {};
  huddle.selected = 'all';
  huddle.openId = null;
  server.items = [mk(1, { thread: [ASKED()] }), mk(2, { thread: [msg(20, 2, 'question', 'an old plain question?')] })];
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function mountBody(popout: boolean): Promise<HTMLElement> {
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

describe('pure', () => {
  test('askParts is null for a plain message and for an empty list', () => {
    expect(askParts({})).toBeNull();
    expect(askParts({ context: 'x', questions: [] })).toBeNull();
    expect(askParts({ context: 'x', questions: ['q'] })).toEqual({ context: 'x', questions: ['q'] });
  });
  test('the reply hints a number only for an open numbered question', () => {
    expect(hasNumberedAsk({ thread: [ASKED()] } as never)).toBe(true);
    expect(hasNumberedAsk({ thread: [{ ...ASKED(), answered: true }] } as never)).toBe(false);
    expect(hasNumberedAsk({ thread: [msg(20, 2, 'question', 'plain')] } as never)).toBe(false);
  });
});

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  test('the row shows the context apart, the numbered questions, then the reply box with the number hint', async () => {
    const host = await mountBody(popout);
    const block = host.querySelector<HTMLElement>('[data-huddle-item="1"] [data-task-manager-questions="1"]')!;
    const ask = block.querySelector<HTMLElement>('[data-task-manager-ask="10"]')!;
    expect(ask.querySelector('[data-task-manager-ask-context]')!.textContent).toBe('two ways to install');
    const list = ask.querySelector<HTMLElement>('ol[data-task-manager-ask-list]')!;
    expect([...list.querySelectorAll('li')].map((li) => li.textContent)).toEqual(['a or b?', 'tonight?']);
    expect(ask.querySelector('[data-task-manager-ask-context]')!.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(block.textContent).not.toContain('1. a or b?');
    const reply = (block.nextElementSibling as HTMLElement).querySelector<HTMLTextAreaElement>('textarea[data-huddle-reply="1"]')!;
    expect(reply.placeholder).toBe('answer by number: 1 ..., 2 ...');
  });

  test('an old text-only question renders as before, with the plain placeholder', async () => {
    const host = await mountBody(popout);
    const block = host.querySelector<HTMLElement>('[data-huddle-item="2"] [data-task-manager-questions="2"]')!;
    expect(block.querySelector('[data-task-manager-ask]')).toBeNull();
    expect(block.querySelector('.tkm-post-text')!.textContent).toBe('an old plain question?');
    expect(host.querySelector<HTMLTextAreaElement>('textarea[data-huddle-reply="2"]')!.placeholder).toBe('reply to claude');
  });

  test('the open item draws the same split in its thread', async () => {
    const host = await mountBody(popout);
    huddle.openId = 1;
    await settle();
    const msgEl = host.querySelector<HTMLElement>('[data-task-manager-thread="1"] [data-task-manager-message="10"]')!;
    expect(msgEl.querySelector('[data-task-manager-ask-context]')!.textContent).toBe('two ways to install');
    expect(msgEl.querySelectorAll('ol[data-task-manager-ask-list] li').length).toBe(2);
  });
});
