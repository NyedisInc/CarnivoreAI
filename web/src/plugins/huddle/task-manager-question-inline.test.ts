/** @vitest-environment jsdom */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const msg = (id: number, item: number, kind: string, text: string, extra: Record<string, unknown> = {}) =>
  ({ id, item_id: item, author: 'claude', kind, text, answered: false, created_at: id, seq: id, ...extra });

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: 7, status: 'open', section: 'open', ...extra,
});

const server = vi.hoisted(() => ({ density: 'normal', items: [] as unknown[], calls: [] as { path: string; body: unknown }[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      server.calls.push({ path, body: init.body ? JSON.parse(String(init.body)) : null });
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'status', density: server.density } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 3, open: 3, review: 0, questions: 1, claude_seq: 0, unread: 0 }] };
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
import { KIND_COLORS, POST_KINDS, QUESTION_BLOCK, openQuestions } from './task-manager-posts';
import { latestMessage, rowParts } from './huddle-density';
import { waitingMarks } from './task-manager-waiting';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

const LIST = () => [
  mk(1, {
    status: 'question', section: 'question', info_unseen: true, info_unread: 1,
    thread: [msg(10, 1, 'question', 'which of the seven wordpress installs do you want first?'), msg(11, 1, 'info', 'the newer info text', { unread: true })],
  }),
  mk(2, { attention_unseen: true, attention_unread: 1, thread: [msg(20, 2, 'attention', 'a look at this', { unread: true })] }),
];

beforeEach(() => {
  statusFolds.choices = {};
  huddle.selected = 'all';
  huddle.openId = null;
  server.calls = [];
  server.items = LIST();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function mountBody(density: string, popout: boolean): Promise<HTMLElement> {
  server.density = density;
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

describe('pure rules', () => {
  test('the open question wins over a newer info for the preview, and normal shows it in a block instead of the one-liner', () => {
    const item = LIST()[0] as never;
    expect(openQuestions(item).map((m) => m.id)).toEqual([10]);
    expect(latestMessage(item)?.id).toBe(10);
    expect(rowParts('compact', item).latest).toBe(true);
    expect(rowParts('normal', item)).toMatchObject({ questions: true, latest: false, reply: true, posts: 'block' });
    expect(rowParts('compact', item).questions).toBe(false);
    const answered = { ...(item as object), thread: [msg(10, 1, 'question', 'q', { answered: true }), msg(11, 1, 'info', 'i', { unread: true })] } as never;
    expect(latestMessage(answered)?.id).toBe(11);
    expect(rowParts('normal', answered).questions).toBe(false);
  });
});

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  test.each(['normal', 'full'])('%s: the open question shows in full, the newer info after it, the reply box at the foot of the feed', async (density) => {
    const host = await mountBody(density, popout);
    const q = host.querySelector<HTMLElement>('[data-huddle-item="1"] [data-task-manager-post-kind="question"]')!;
    expect(q.textContent).toContain('which of the seven wordpress installs do you want first?');
    const block = host.querySelector<HTMLElement>('[data-task-manager-questions="1"]')!;
    const box = block.nextElementSibling as HTMLElement;
    expect(box.getAttribute('data-task-manager-question-reply')).toBe('1');
    expect(box.querySelector('textarea[data-huddle-reply="1"]')).not.toBeNull();
    expect(host.querySelectorAll('[data-huddle-item="1"] [data-task-manager-reply-on-row]').length).toBe(1);
    const info = host.querySelector<HTMLElement>('[data-huddle-item="1"] [data-task-manager-post-kind="info"]')!;
    expect(info.textContent).toContain('the newer info text');
    expect(q.compareDocumentPosition(info) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(info.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(host.querySelector('[data-task-manager-latest="1"]')).toBeNull();
  });

  test('compact: the one-line text is the question, not the newer info; no block, no reply box', async () => {
    const host = await mountBody('compact', popout);
    huddle.openId = null;
    await settle();
    expect(host.querySelector('[data-task-manager-latest="1"] .tkm-latest-text')!.textContent).toBe('which of the seven wordpress installs do you want first?');
    expect(host.querySelector('[data-task-manager-questions]')).toBeNull();
    expect(host.querySelector('[data-task-manager-reply-on-row]')).toBeNull();
  });

  test('replying posts the message and the answered question leaves the block', async () => {
    const host = await mountBody('normal', popout);
    const box = host.querySelector<HTMLTextAreaElement>('[data-huddle-reply="1"]')!;
    box.value = 'the first one';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await settle();
    expect(server.calls.some((c) => c.path === '/cplugs/huddle/items/1/messages' && (c.body as { text: string }).text === 'the first one')).toBe(true);
    server.items = [mk(1, { status: 'working', section: 'working', thread: [msg(10, 1, 'question', 'q', { answered: true }), msg(12, 1, 'reply', 'the first one', { author: 'joe' })] }), mk(2)];
    await refreshTaskManager();
    await settle();
    expect(host.querySelector('[data-task-manager-questions="1"]')).toBeNull();
  });

  test('question, info and look wear three different tokens on their blocks', async () => {
    const host = await mountBody('normal', popout);
    const tone = (kind: string, id: number): string =>
      host.querySelector<HTMLElement>(`[data-huddle-item="${id}"] [data-task-manager-post-kind="${kind}"]`)!.style.getPropertyValue('--_post');
    const [q, i, l] = [tone('question', 1), tone('info', 1), tone('attention', 2)];
    expect([q, i, l]).toEqual(['var(--oc-yellow-bright)', 'var(--oc-violet)', 'var(--oc-cyan)']);
    expect(new Set([q, i, l]).size).toBe(3);
  });
});

describe('the three colors', () => {
  test('one table feeds the blocks, the counts and the folded header marks', () => {
    expect(QUESTION_BLOCK.color).toBe(KIND_COLORS.question.color);
    expect(POST_KINDS.info.color).toBe(KIND_COLORS.info.color);
    expect(POST_KINDS.attention.color).toBe(KIND_COLORS.look.color);
    const marks = waitingMarks(LIST() as never);
    const color = Object.fromEntries(marks.map((m) => [m.kind, m.color]));
    expect(color).toEqual({ question: KIND_COLORS.question.color, info: KIND_COLORS.info.color });
    expect(new Set(Object.values(color)).size).toBe(2);
  });

  test('the tokens are real and stay apart under every shipped theme', () => {
    const tokens = readFileSync(resolve(process.cwd(), 'src/opscenter/tokens.css'), 'utf8');
    for (const name of ['--oc-yellow-bright', '--oc-violet', '--oc-cyan']) expect(tokens).toMatch(new RegExp(`${name}:`));
    expect(tokens).toMatch(/--oc-yellow-bright: var\(--color-warning/);
    expect(tokens).toMatch(/--oc-cyan: var\(--color-info/);
    const root = resolve(process.cwd(), '../client/css/themes');
    const themes = readdirSync(root).filter((d) => existsSync(`${root}/${d}/theme.json`));
    expect(themes.length).toBeGreaterThan(2);
    for (const theme of themes) {
      const vars = (JSON.parse(readFileSync(`${root}/${theme}/theme.json`, 'utf8')) as { cssVars: Record<string, string> }).cssVars;
      const warning = vars['--color-warning']?.toLowerCase();
      const info = vars['--color-info']?.toLowerCase();
      expect(warning && info && warning !== info, theme).toBe(true);
      expect([warning, info]).not.toContain('#a98fe0');
    }
  });
});
