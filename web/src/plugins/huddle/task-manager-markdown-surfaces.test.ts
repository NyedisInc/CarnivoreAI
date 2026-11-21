/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const MD = '***bold italic*** then **bold** and *it* with `code`';
const LONG_POST = `**a long bold opening that runs on ${'and on '.repeat(40)}past the fold** then *more* \`code\``;
const msg = (id: number, kind: string, text: string, extra: Record<string, unknown> = {}) =>
  ({ id, item_id: 1, author: 'claude', kind, text, answered: false, created_at: id, seq: id, ...extra });
const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `${MD} in the text`, note: '', position: id, created_by: 'claude', state: 'open', kind: '', number: id,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: 7, status: 'open', section: 'open', ...extra,
});

const ASK = {
  item: 3, message: 30, typed: true, answered: false, answer_message_id: null,
  ask: { context: `**context:** ${MD}`, questions: [
    { id: 'go', type: 'yes_no', prompt: `ship ${MD}?`, help: 'a ***help*** line', required: true, recommend: { value: true, reason: 'one **system**' } },
    { id: 'pick', type: 'single', prompt: 'which *one*?', required: true, options: [
      { id: 'a', label: 'only **this** list', recommended: true, reason: 'the `same` *view*' }, { id: 'b', label: '*every* project' }] },
  ] },
};

const server = vi.hoisted(() => ({ items: [] as unknown[], density: 'normal' }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'status', density: server.density } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/questions/30') return ASK;
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
import { cplugEnablement } from '../host/enablement.svelte';
import HuddleBody from './HuddleBody.svelte';
import TaskManagerAskForm from './ask/TaskManagerAskForm.svelte';
import { FOLD_CHARS } from './task-manager-posts';

cplugEnablement.enabled = { huddle: true };
let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

async function mountBody(density: string): Promise<HTMLElement> {
  server.density = density;
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false } });
  await settle();
  return host;
}

function expectNoMarkers(el: Element | null): void {
  expect(el).not.toBeNull();
  expect(el?.textContent ?? '').not.toMatch(/[*`]/);
}

function expectStyled(el: Element | null): void {
  expect(el?.querySelector('strong > em')?.textContent).toBe('bold italic');
  expect([...(el?.querySelectorAll('strong') ?? [])].some((n) => n.textContent === 'bold')).toBe(true);
  expect([...(el?.querySelectorAll('em') ?? [])].some((n) => n.textContent === 'it')).toBe(true);
  expect(el?.querySelector('code.hmd-code')?.textContent).toBe('code');
}

beforeEach(() => {
  statusFolds.choices = {};
  huddle.selected = 'all';
  huddle.openId = null;
  server.items = [
    mk(1, { created_by: 'joe', title: `${MD} and a title long enough to be cut at the row's edge` }),
    mk(2, { title: 'a post', info_unseen: true, info_unread: 1, thread: [msg(20, 'info', LONG_POST, { item_id: 2, unread: true })] }),
    mk(3, { title: `question ${MD}`, status: 'question', section: 'question', thread: [msg(31, 'question', `1. ship ${MD}?`, { item_id: 3 })] }),
  ];
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('rows', () => {
  test('the title line draws bold italic, bold, italic and code, no marker, inside its clipping host', async () => {
    const host = await mountBody('normal');
    const title = host.querySelector('[data-task-manager-row-title="1"]');
    expectNoMarkers(title);
    expectStyled(title);
    expect(title?.className).toMatch(/tkm-text--clip/);
    expect(title?.querySelector('[data-task-manager-md-inline]')).not.toBeNull();
  });

  test('a long post folds on the parsed tree: bold kept up to the cut, an ellipsis, no marker; open shows it whole', async () => {
    const host = await mountBody('normal');
    const post = host.querySelector<HTMLElement>('[data-task-manager-post="20"]');
    expect(post?.getAttribute('data-task-manager-post-folded')).toBe('true');
    const text = post?.querySelector('.tkm-post-text');
    expectNoMarkers(text);
    expect(text?.querySelector('strong')?.textContent).toMatch(/^a long bold opening/);
    expect((text?.textContent ?? '').trim().endsWith('…')).toBe(true);
    expect((text?.textContent ?? '').trim().length).toBeLessThanOrEqual(FOLD_CHARS + 1);
    post?.querySelector<HTMLElement>('[data-task-manager-post-fold="20"]')?.click();
    await settle();
    const whole = host.querySelector('[data-task-manager-post="20"] .tkm-post-text');
    expectNoMarkers(whole);
    expect(whole?.querySelector('em')?.textContent).toBe('more');
    expect(whole?.querySelector('code')?.textContent).toBe('code');
  });

  test('the open question on the row draws markdown, whoever wrote it', async () => {
    const host = await mountBody('normal');
    const question = host.querySelector('[data-task-manager-post="31"]');
    expectNoMarkers(question);
    expectStyled(question);
  });

  test('full density: the description draws markdown', async () => {
    const host = await mountBody('full');
    const desc = host.querySelector('[data-task-manager-peek-description="1"]');
    expectNoMarkers(desc);
    expectStyled(desc);
  });

  test('compact density: the latest line is one styled inline run under its ellipsis, its tooltip plain', async () => {
    server.items = [mk(3, { status: 'question', section: 'question', thread: [msg(31, 'question', `1. ship ${MD}?`, { item_id: 3, answered: true })] })];
    const host = await mountBody('compact');
    const latest = host.querySelector('[data-task-manager-latest="3"]');
    expectNoMarkers(latest);
    expectStyled(latest);
    expect(latest?.getAttribute('title')).toBe('ship bold italic then bold and it with code?');
  });
});

describe('the answer popup', () => {
  test('the item name, context, prompts, help, options and reasons draw markdown, no marker anywhere', async () => {
    huddle.body = { list: 'all', items: [{ id: 3, list: 'all', text: 'x', title: `question ${MD}`, thread: [] }] } as never;
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(TaskManagerAskForm, { target: host, props: { messageId: 30, mode: 'panel', onClose: () => undefined } });
    await settle();
    const form = host.querySelector('[data-ask-form="30"]');
    expectNoMarkers(form);
    expectStyled(form?.querySelector('.hdq-name') ?? null);
    expectStyled(form?.querySelector('.hdq-context') ?? null);
    expectStyled(form?.querySelector('[data-qid="go"] .hdq-prompt') ?? null);
    expect(form?.querySelector('.hdq-help strong > em')?.textContent).toBe('help');
    expect(form?.querySelector('[data-qid="pick"] .hdq-prompt em')?.textContent).toBe('one');
    expect([...(form?.querySelectorAll('[data-qid="pick"] strong') ?? [])].some((n) => n.textContent === 'this')).toBe(true);
    expect(form?.querySelector('[data-qid="pick"] .hdq-why code')?.textContent).toBe('same');
    expect(form?.querySelector('[data-ask-field="go"]')?.getAttribute('aria-label')).toBe('ship bold italic then bold and it with code?');
  });
});
